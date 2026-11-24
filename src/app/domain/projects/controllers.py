"""Project & Board: boards, task lists, cards, checklists, comments and board members."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody, QueryParameter
from litestar.status_codes import HTTP_204_NO_CONTENT
from sqlalchemy import and_, case, exists, func, or_, select, update

from app.db import models as m
from app.domain.accounts.guards import requires_permission
from app.domain.accounts.schemas import UserSummary
from app.domain.organization.scope import ListQuery, company_members, provide_list_query
from app.domain.projects.schemas import (
    Board,
    BoardCreate,
    BoardDetail,
    BoardMember,
    BoardUpdate,
    ChecklistCreate,
    ChecklistItem,
    ChecklistUpdate,
    Comment,
    CommentCreate,
    ListCreate,
    ListUpdate,
    MemberAdd,
    MemberUpdate,
    Task,
    TaskCreate,
    TaskDetail,
    TaskList,
    TaskMove,
    TaskUpdate,
)
from app.domain.projects.services import (
    BoardAccess,
    BoardService,
    TaskService,
    access_for,
    load_access,
    provide_board_service,
    provide_task_service,
    require,
)
from app.lib.exceptions import ApplicationClientError
from app.lib.schema import Paginated

can_read = requires_permission(m.AppModule.PROJECTS, m.PermissionAction.READ)
can_create = requires_permission(m.AppModule.PROJECTS, m.PermissionAction.CREATE)
can_update = requires_permission(m.AppModule.PROJECTS, m.PermissionAction.UPDATE)
can_delete = requires_permission(m.AppModule.PROJECTS, m.PermissionAction.DELETE)

DEFAULT_LISTS = ("To Do", "In Progress", "Review", "Pending Tasks")
"""Lists a new board starts with, as in the Figma board."""

READ_ONLY = "You can only view this board"
MANAGE_ONLY = "Only board admins can do this"


class ProjectController(Controller):
    path = "/projects"
    tags = ["Project & Board"]
    dependencies = {
        "boards_service": Provide(provide_board_service),
        "tasks_service": Provide(provide_task_service),
        "list_query": Provide(provide_list_query, sync_to_thread=False),
    }

    # ---------- boards ----------
    @get("/boards", operation_id="ListBoards", guards=[can_read])
    async def list_boards(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[Board]:
        """Boards the user can see, newest first. Filter with `business`, `status` and `search` (title)."""
        session = boards_service.repository.session
        stats = _stats_subquery()
        total, done = func.coalesce(stats.c.total, 0), func.coalesce(stats.c.done, 0)
        status = _status_expr(total, done)
        statement = select(m.Board, total, func.coalesce(stats.c.due, m.Board.due_date), status).outerjoin(
            stats, stats.c.board_id == m.Board.id
        )

        # The selected company's boards: private ones only for their members.
        filters: list[Any] = [m.Board.business_id == company.id]
        if not current_user.is_superuser:
            is_member = exists().where(m.BoardMember.board_id == m.Board.id, m.BoardMember.user_id == current_user.id)
            filters.append(or_(is_member, m.Board.visibility != m.Visibility.PRIVATE))
        if list_query.search:
            filters.append(m.Board.title.ilike(f"%{_escape(list_query.search)}%", escape="\\"))
        if list_query.status:
            try:
                filters.append(status == m.BoardStatus(list_query.status).value)
            except ValueError:
                raise ApplicationClientError(f"Unknown status '{list_query.status}'") from None
        statement = statement.where(*filters)

        count = await session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = await session.execute(
            statement.order_by(m.Board.created_at.desc()).limit(list_query.page_size).offset(list_query.offset)
        )
        items = [
            _board(board, task_count=task_count, due=due, status=m.BoardStatus(row_status))
            for board, task_count, due, row_status in rows.unique()
        ]
        return Paginated(items=items, total=count or 0, page=list_query.page, page_size=list_query.page_size)

    @post("/boards", operation_id="CreateBoard", guards=[can_create])
    async def create_board(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[BoardCreate],
    ) -> Board:
        """New board with the default lists. The creator becomes its admin."""
        session = boards_service.repository.session
        business = company
        board = m.Board(
            business_id=business.id, title=data.title, visibility=data.visibility, created_by=current_user.id
        )
        board.business = business
        board = await boards_service.create(board)
        session.add(m.BoardMember(board_id=board.id, user_id=current_user.id, access=m.BoardAccess.ADMIN))
        session.add_all(m.TaskList(board_id=board.id, title=t, position=i) for i, t in enumerate(DEFAULT_LISTS))
        await session.flush()
        return _board(board, task_count=0, due=board.due_date, status=m.BoardStatus.PLANNING)

    @get("/boards/{board_id:uuid}", operation_id="GetBoard", guards=[can_read])
    async def get_board(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
    ) -> BoardDetail:
        """The board view: lists with their (non-archived) cards, members and what the user may do."""
        access = await load_access(boards_service, current_user, board_id, company)
        return await _board_detail(boards_service, access)

    @patch("/boards/{board_id:uuid}", operation_id="UpdateBoard", guards=[can_update])
    async def update_board(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
        data: JSONBody[BoardUpdate],
    ) -> BoardDetail:
        """Rename (editors) or change visibility (board admins)."""
        access = await load_access(boards_service, current_user, board_id, company)
        changes = data.to_dict()
        require(access.can_manage if "visibility" in changes else access.can_edit, MANAGE_ONLY)
        for key, value in changes.items():
            setattr(access.board, key, value)
        await boards_service.update(access.board)
        return await _board_detail(boards_service, access)

    @delete("/boards/{board_id:uuid}", operation_id="DeleteBoard", guards=[can_delete])
    async def delete_board(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
    ) -> None:
        access = await load_access(boards_service, current_user, board_id, company)
        require(access.can_manage, MANAGE_ONLY)
        await boards_service.delete(access.board.id)

    # ---------- members ----------
    @post("/boards/{board_id:uuid}/members", operation_id="AddBoardMember", guards=[can_update])
    async def add_member(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
        data: JSONBody[MemberAdd],
    ) -> BoardMember:
        """ "Share Board": add someone by email, full name or id."""
        access = await load_access(boards_service, current_user, board_id, company)
        require(access.can_manage, MANAGE_ONLY)
        session = boards_service.repository.session
        user = await _find_user(session, data.user)
        if user is None or not user.is_active or not (user.is_superuser or user.membership(access.board.business_id)):
            raise ApplicationClientError(f"No active user '{data.user}' works in {access.board.business.name}")
        existing = await session.scalar(
            select(m.BoardMember).where(m.BoardMember.board_id == board_id, m.BoardMember.user_id == user.id)
        )
        if existing is not None:
            raise ApplicationClientError(f"{user.name} is already on this board")
        member = m.BoardMember(board_id=board_id, user_id=user.id, access=data.access)
        member.user = user
        session.add(member)
        await session.flush()
        return _member(member, company.id)

    @patch("/board-members/{member_id:uuid}", operation_id="UpdateBoardMember", guards=[can_update])
    async def update_member(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        member_id: FromPath[UUID],
        data: JSONBody[MemberUpdate],
    ) -> BoardMember:
        member, _ = await _managed_member(boards_service, current_user, company, member_id)
        if member.access == m.BoardAccess.ADMIN and data.access != m.BoardAccess.ADMIN:
            await _keep_an_admin(boards_service, member)
        member.access = data.access
        await boards_service.repository.session.flush()
        return _member(member, company.id)

    @delete("/board-members/{member_id:uuid}", operation_id="RemoveBoardMember", guards=[can_update])
    async def remove_member(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        member_id: FromPath[UUID],
    ) -> None:
        member, _ = await _managed_member(boards_service, current_user, company, member_id)
        if member.access == m.BoardAccess.ADMIN:
            await _keep_an_admin(boards_service, member)
        await boards_service.repository.session.delete(member)

    # ---------- lists ----------
    @post("/boards/{board_id:uuid}/lists", operation_id="CreateTaskList", guards=[can_update])
    async def create_list(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
        data: JSONBody[ListCreate],
    ) -> TaskList:
        access = await load_access(boards_service, current_user, board_id, company)
        require(access.can_edit, READ_ONLY)
        session = boards_service.repository.session
        position = await session.scalar(
            select(func.coalesce(func.max(m.TaskList.position) + 1, 0)).where(m.TaskList.board_id == board_id)
        )
        task_list = m.TaskList(board_id=board_id, title=data.title, position=position)
        session.add(task_list)
        await session.flush()
        return TaskList(id=task_list.id, title=task_list.title, position=task_list.position, tasks=[])

    @patch("/lists/{list_id:uuid}", operation_id="UpdateTaskList", guards=[can_update])
    async def update_list(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_id: FromPath[UUID],
        data: JSONBody[ListUpdate],
    ) -> TaskList:
        task_list, _ = await _editable_list(boards_service, current_user, company, list_id)
        for key, value in data.to_dict().items():
            setattr(task_list, key, value)
        await boards_service.repository.session.flush()
        return TaskList(id=task_list.id, title=task_list.title, position=task_list.position, tasks=[])

    @delete("/lists/{list_id:uuid}", operation_id="DeleteTaskList", guards=[can_update])
    async def delete_list(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_id: FromPath[UUID],
    ) -> None:
        """Deletes the list and every card in it."""
        task_list, _ = await _editable_list(boards_service, current_user, company, list_id)
        await boards_service.repository.session.delete(task_list)

    # ---------- cards ----------
    @post("/lists/{list_id:uuid}/tasks", operation_id="CreateTask", guards=[can_update])
    async def create_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_id: FromPath[UUID],
        data: JSONBody[TaskCreate],
    ) -> Task:
        """ "Add a task" at the bottom of a list."""
        task_list, _ = await _editable_list(boards_service, current_user, company, list_id)
        task = m.Task(
            board_id=task_list.board_id,
            list_id=task_list.id,
            title=data.title,
            position=await _bottom(tasks_service, task_list.id),
        )
        task.members, task.checklist = [], []
        return Task.from_model(await tasks_service.create(task))

    @get("/tasks/{task_id:uuid}", operation_id="GetTask", guards=[can_read])
    async def get_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
    ) -> TaskDetail:
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        return await _task_detail(tasks_service, task, access)

    @patch("/tasks/{task_id:uuid}", operation_id="UpdateTask", guards=[can_update])
    async def update_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
        data: JSONBody[TaskUpdate],
    ) -> TaskDetail:
        """Labels, dates, members, cover, description, title, or mark complete."""
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        require(access.can_edit, READ_ONLY)
        changes = data.to_dict()
        if "completed" in changes:
            task.completed_at = datetime.now(UTC) if changes.pop("completed") else None
        if "member_ids" in changes:
            task.members = await _board_users(tasks_service, task.board_id, changes.pop("member_ids"))
        if "cover" in changes:
            task.cover_url = changes.pop("cover")
        if "labels" in changes:
            task.labels = list(dict.fromkeys(label.strip() for label in changes.pop("labels")))
        for key, value in changes.items():
            setattr(task, key, value)
        task = await tasks_service.update(task)
        return await _task_detail(tasks_service, task, access)

    @post("/tasks/{task_id:uuid}/move", operation_id="MoveTask", guards=[can_update])
    async def move_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
        data: JSONBody[TaskMove],
    ) -> TaskDetail:
        """Move to another list, on this board or another one you can edit."""
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        require(access.can_edit, READ_ONLY)
        target, target_access = await _editable_list(boards_service, current_user, company, data.list_id)
        session = tasks_service.repository.session
        if isinstance(data.position, int):
            # Drag and drop: renumber the target list with the card at the requested index.
            siblings = list(
                (
                    await session.scalars(
                        select(m.Task)
                        .where(m.Task.list_id == target.id, m.Task.id != task.id, m.Task.archived_at.is_(None))
                        .order_by(m.Task.position, m.Task.created_at)
                    )
                ).unique()
            )
            siblings.insert(min(data.position, len(siblings)), task)
            for index, sibling in enumerate(siblings):
                sibling.position = index
        elif data.position == "top":
            await session.execute(
                update(m.Task)
                .where(m.Task.list_id == target.id, m.Task.id != task.id)
                .values(position=m.Task.position + 1)
            )
            task.position = 0
        else:
            task.position = await _bottom(tasks_service, target.id)
        if target.board_id != task.board_id:
            # Members who aren't on the new board are dropped from the card.
            allowed = {mem.user_id for mem in await _members(session, target.board_id)}
            task.members = [u for u in task.members if u.id in allowed]
        task.list_id, task.board_id = target.id, target.board_id
        task = await tasks_service.update(task)
        return await _task_detail(tasks_service, task, target_access)

    @post("/tasks/{task_id:uuid}/copy", operation_id="CopyTask", guards=[can_update])
    async def copy_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
    ) -> Task:
        """ "Copy card": a copy right below the original, with labels, members, dates and checklist."""
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        require(access.can_edit, READ_ONLY)
        session = tasks_service.repository.session
        await session.execute(
            update(m.Task)
            .where(m.Task.list_id == task.list_id, m.Task.position > task.position)
            .values(position=m.Task.position + 1)
        )
        copy = m.Task(
            board_id=task.board_id,
            list_id=task.list_id,
            title=task.title,
            description=task.description,
            cover_url=task.cover_url,
            due_date=task.due_date,
            labels=list(task.labels or []),
            position=task.position + 1,
        )
        copy.members = list(task.members)
        copy.checklist = [m.ChecklistItem(text=c.text, done=c.done, position=c.position) for c in task.checklist]
        return Task.from_model(await tasks_service.create(copy))

    @post(
        "/tasks/{task_id:uuid}/archive",
        operation_id="ArchiveTask",
        guards=[can_update],
        status_code=HTTP_204_NO_CONTENT,
    )
    async def archive_task(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
    ) -> None:
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        require(access.can_edit, READ_ONLY)
        task.archived_at = datetime.now(UTC)
        await tasks_service.update(task)

    # ---------- checklist ----------
    @post("/tasks/{task_id:uuid}/checklist", operation_id="AddChecklistItem", guards=[can_update])
    async def add_checklist_item(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
        data: JSONBody[ChecklistCreate],
    ) -> ChecklistItem:
        task, access = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        require(access.can_edit, READ_ONLY)
        item = m.ChecklistItem(task_id=task.id, text=data.text, position=len(task.checklist))
        task.checklist.append(item)
        await tasks_service.update(task)
        return ChecklistItem(id=item.id, text=item.text, done=item.done)

    @patch("/checklist-items/{item_id:uuid}", operation_id="UpdateChecklistItem", guards=[can_update])
    async def update_checklist_item(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        item_id: FromPath[UUID],
        data: JSONBody[ChecklistUpdate],
    ) -> ChecklistItem:
        item = await _editable_item(boards_service, tasks_service, current_user, company, item_id)
        for key, value in data.to_dict().items():
            setattr(item, key, value)
        await tasks_service.repository.session.flush()
        return ChecklistItem(id=item.id, text=item.text, done=item.done)

    @delete("/checklist-items/{item_id:uuid}", operation_id="DeleteChecklistItem", guards=[can_update])
    async def delete_checklist_item(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        item_id: FromPath[UUID],
    ) -> None:
        item = await _editable_item(boards_service, tasks_service, current_user, company, item_id)
        await tasks_service.repository.session.delete(item)

    # ---------- comments ----------
    @get("/tasks/{task_id:uuid}/comments", operation_id="ListTaskComments", guards=[can_read])
    async def list_comments(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
    ) -> list[Comment]:
        task, _ = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        comments = await tasks_service.repository.session.scalars(
            select(m.TaskComment).where(m.TaskComment.task_id == task.id).order_by(m.TaskComment.created_at.desc())
        )
        return [Comment.from_model(c) for c in comments.unique()]

    @post("/tasks/{task_id:uuid}/comments", operation_id="AddTaskComment", guards=[can_read])
    async def add_comment(
        self,
        boards_service: NamedDependency[BoardService],
        tasks_service: NamedDependency[TaskService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        task_id: FromPath[UUID],
        data: JSONBody[CommentCreate],
    ) -> Comment:
        """Anyone who can see the card can comment, including Viewers."""
        task, _ = await _visible_task(boards_service, tasks_service, current_user, company, task_id)
        comment = m.TaskComment(task_id=task.id, author_id=current_user.id, body=data.body)
        comment.author = current_user
        session = tasks_service.repository.session
        session.add(comment)
        await session.flush()
        return Comment.from_model(comment)

    @get("/boards/{board_id:uuid}/candidates", operation_id="ListBoardCandidates", guards=[can_read])
    async def list_candidates(
        self,
        boards_service: NamedDependency[BoardService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        board_id: FromPath[UUID],
        search: Annotated[str | None, QueryParameter(max_length=100)] = None,
    ) -> list[UserSummary]:
        """People who could be added in "Share Board": the company's members not yet on the board."""
        access = await load_access(boards_service, current_user, board_id, company)
        session = boards_service.repository.session
        on_board = {mem.user_id for mem in await _members(session, board_id)}
        term = (search or "").strip().lower()
        return [
            UserSummary.from_user(u, company.id)
            for u in await company_members(session, access.board.business_id)
            if u.id not in on_board and (not term or term in u.name.lower() or term in u.email.lower())
        ]


# ---------- helpers ----------
def _escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _stats_subquery() -> Any:
    return (
        select(
            m.Task.board_id.label("board_id"),
            func.count(m.Task.id).label("total"),
            func.count(m.Task.completed_at).label("done"),
            func.max(m.Task.due_date).label("due"),
        )
        .where(m.Task.archived_at.is_(None))
        .group_by(m.Task.board_id)
        .subquery()
    )


def _status_expr(total: Any, done: Any) -> Any:
    """Completed when every card is done, In Progress once one is, otherwise Planning."""
    return case(
        (and_(total > 0, done == total), m.BoardStatus.COMPLETED.value),
        (done > 0, m.BoardStatus.IN_PROGRESS.value),
        else_=m.BoardStatus.PLANNING.value,
    )


def _status(total: int, done: int) -> m.BoardStatus:
    if total and done == total:
        return m.BoardStatus.COMPLETED
    return m.BoardStatus.IN_PROGRESS if done else m.BoardStatus.PLANNING


def _board(board: m.Board, *, task_count: int, due: Any, status: m.BoardStatus) -> Board:
    return Board(
        id=board.id,
        business=board.business.name,
        business_id=board.business_id,
        title=board.title,
        status=status,
        task_count=task_count,
        due_date=due,
        visibility=board.visibility,
    )


def _member(member: m.BoardMember, business_id: UUID) -> BoardMember:
    summary = UserSummary.from_user(member.user, business_id)
    return BoardMember(
        **{f: getattr(summary, f) for f in UserSummary.__struct_fields__},
        member_id=member.id,
        access=member.access,
        label=member.label or summary.role,
    )


async def _members(session: Any, board_id: UUID) -> list[m.BoardMember]:
    access_order = case(
        (m.BoardMember.access == m.BoardAccess.ADMIN, 0), (m.BoardMember.access == m.BoardAccess.MEMBER, 1), else_=2
    )
    rows = await session.scalars(
        select(m.BoardMember).where(m.BoardMember.board_id == board_id).order_by(access_order, m.BoardMember.created_at)
    )
    return list(rows.unique())


async def _attachment_counts(session: Any, task_ids: list[UUID]) -> dict[UUID, int]:
    if not task_ids:
        return {}
    rows = await session.execute(
        select(m.TaskAttachment.task_id, func.count())
        .where(m.TaskAttachment.task_id.in_(task_ids))
        .group_by(m.TaskAttachment.task_id)
    )
    return dict(rows.all())


async def _board_detail(boards: BoardService, access: BoardAccess) -> BoardDetail:
    session = boards.repository.session
    board = access.board
    lists = (
        await session.scalars(
            select(m.TaskList)
            .where(m.TaskList.board_id == board.id)
            .order_by(m.TaskList.position, m.TaskList.created_at)
        )
    ).all()
    tasks = (
        (
            await session.scalars(
                select(m.Task)
                .where(m.Task.board_id == board.id, m.Task.archived_at.is_(None))
                .order_by(m.Task.position, m.Task.created_at)
            )
        )
        .unique()
        .all()
    )
    counts = await _attachment_counts(session, [t.id for t in tasks])
    by_list: dict[UUID, list[Task]] = {tl.id: [] for tl in lists}
    for t in tasks:
        by_list.setdefault(t.list_id, []).append(Task.from_model(t, counts.get(t.id, 0)))
    dues = [t.due_date for t in tasks if t.due_date]
    summary = _board(
        board,
        task_count=len(tasks),
        due=max(dues) if dues else board.due_date,
        status=_status(len(tasks), sum(1 for t in tasks if t.completed_at)),
    )
    return BoardDetail(
        **{f: getattr(summary, f) for f in Board.__struct_fields__},
        lists=[TaskList(id=tl.id, title=tl.title, position=tl.position, tasks=by_list[tl.id]) for tl in lists],
        members=[_member(mem, board.business_id) for mem in await _members(session, board.id)],
        can_edit=access.can_edit,
        can_manage=access.can_manage,
    )


async def _task_detail(tasks: TaskService, task: m.Task, access: BoardAccess) -> TaskDetail:
    session = tasks.repository.session
    list_title = await session.scalar(select(m.TaskList.title).where(m.TaskList.id == task.list_id))
    counts = await _attachment_counts(session, [task.id])
    return TaskDetail.build(task, list_title or "", counts.get(task.id, 0), access.can_edit)


async def _bottom(tasks: TaskService, list_id: UUID) -> int:
    return await tasks.repository.session.scalar(
        select(func.coalesce(func.max(m.Task.position) + 1, 0)).where(m.Task.list_id == list_id)
    )


async def _editable_list(
    boards: BoardService, user: m.User, company: m.Business, list_id: UUID
) -> tuple[m.TaskList, BoardAccess]:
    task_list = await boards.repository.session.get(m.TaskList, list_id)
    if task_list is None:
        raise NotFoundException(detail="List not found")
    access = await load_access(boards, user, task_list.board_id, company)
    require(access.can_edit, READ_ONLY)
    return task_list, access


async def _visible_task(
    boards: BoardService, tasks: TaskService, user: m.User, company: m.Business, task_id: UUID
) -> tuple[m.Task, BoardAccess]:
    task = await tasks.get_one_or_none(m.Task.id == task_id)
    if task is None:
        raise NotFoundException(detail="Card not found")
    return task, await load_access(boards, user, task.board_id, company)


async def _editable_item(
    boards: BoardService, tasks: TaskService, user: m.User, company: m.Business, item_id: UUID
) -> m.ChecklistItem:
    item = await tasks.repository.session.get(m.ChecklistItem, item_id)
    if item is None:
        raise NotFoundException(detail="Checklist item not found")
    _, access = await _visible_task(boards, tasks, user, company, item.task_id)
    require(access.can_edit, READ_ONLY)
    return item


async def _board_users(tasks: TaskService, board_id: UUID, user_ids: list[UUID]) -> list[m.User]:
    members = {mem.user_id: mem.user for mem in await _members(tasks.repository.session, board_id)}
    if missing := [uid for uid in user_ids if uid not in members]:
        raise ApplicationClientError(
            f"{len(missing)} of the chosen people are not on this board. Share it with them first."
        )
    return [members[uid] for uid in dict.fromkeys(user_ids)]


async def _find_user(session: Any, ref: str) -> m.User | None:
    ref = ref.strip()
    try:
        condition: Any = m.User.id == UUID(ref)
    except ValueError:
        condition = or_(m.User.email == ref, func.lower(m.User.name) == ref.lower())
    return (await session.execute(select(m.User).where(condition))).scalars().unique().first()


async def _managed_member(
    boards: BoardService, user: m.User, company: m.Business, member_id: UUID
) -> tuple[m.BoardMember, BoardAccess]:
    member = await boards.repository.session.get(m.BoardMember, member_id)
    if member is None:
        raise NotFoundException(detail="Member not found")
    access = await load_access(boards, user, member.board_id, company)
    require(access.can_manage, MANAGE_ONLY)
    return member, access


async def _keep_an_admin(boards: BoardService, member: m.BoardMember) -> None:
    admins = await boards.repository.session.scalar(
        select(func.count()).where(
            m.BoardMember.board_id == member.board_id, m.BoardMember.access == m.BoardAccess.ADMIN
        )
    )
    if (admins or 0) <= 1:
        raise ApplicationClientError("A board needs at least one admin")


__all__ = ("ProjectController", "access_for")
