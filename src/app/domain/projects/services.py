from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.extensions.litestar.providers import create_service_provider
from litestar.exceptions import NotFoundException, PermissionDeniedException
from sqlalchemy import select

from app.db import models as m

if TYPE_CHECKING:
    from uuid import UUID


class BoardService(service.SQLAlchemyAsyncRepositoryService[m.Board]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Board]):
        model_type = m.Board

    repository_type = Repo


class TaskService(service.SQLAlchemyAsyncRepositoryService[m.Task]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Task]):
        model_type = m.Task

    repository_type = Repo


provide_board_service = create_service_provider(BoardService)
provide_task_service = create_service_provider(TaskService)


@dataclass
class BoardAccess:
    """What the signed-in user may do on one board."""

    board: m.Board
    member: m.BoardMember | None
    can_edit: bool
    can_manage: bool


def access_for(user: m.User, board: m.Board, member: m.BoardMember | None) -> BoardAccess | None:
    """None when the board is invisible to the user.

    - Admins (superusers) can do everything.
    - Private boards are visible to their members only; workspace/public boards to anyone in the business.
    - Editing needs the Projects "update" permission and Admin/Member access on the board (or being its creator).
    - Managing (share, member access, visibility, delete) needs Admin access on the board or being its creator.
    """
    if user.is_superuser:
        return BoardAccess(board, member, can_edit=True, can_manage=True)
    if member is None and (board.visibility == m.Visibility.PRIVATE or not user.membership(board.business_id)):
        return None
    is_creator = board.created_by == user.id
    is_admin = member is not None and member.access == m.BoardAccess.ADMIN
    can_write = is_creator or (member is not None and member.access != m.BoardAccess.VIEWER)
    return BoardAccess(
        board,
        member,
        can_edit=can_write and user.has_permission(m.AppModule.PROJECTS, m.PermissionAction.UPDATE, board.business_id),
        can_manage=is_creator or is_admin,
    )


async def load_access(boards: BoardService, user: m.User, board_id: UUID, company: m.Business) -> BoardAccess:
    """Board plus the user's rights on it. Boards of other companies, and invisible ones, look missing."""
    session = boards.repository.session
    board = await session.get(m.Board, board_id)
    if board is not None and board.business_id != company.id:
        board = None
    member = None
    if board is not None:
        member = await session.scalar(
            select(m.BoardMember).where(m.BoardMember.board_id == board.id, m.BoardMember.user_id == user.id)
        )
    access = access_for(user, board, member) if board is not None else None
    if access is None:
        raise NotFoundException(detail="Board not found")
    return access


def require(allowed: bool, detail: str) -> None:
    if not allowed:
        raise PermissionDeniedException(detail=detail)
