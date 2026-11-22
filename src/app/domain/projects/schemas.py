"""Request and response bodies for Project & Board. Names match the frontend's types."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

import msgspec

from app.db import models as m
from app.domain.accounts.schemas import UserSummary
from app.lib.schema import CamelizedBaseStruct

Title = Annotated[str, msgspec.Meta(min_length=1, max_length=200)]
CardTitle = Annotated[str, msgspec.Meta(min_length=1, max_length=300)]
Label = Annotated[str, msgspec.Meta(min_length=1, max_length=50)]
Url = Annotated[str, msgspec.Meta(max_length=500)]


# ---------- Boards ----------
class Board(CamelizedBaseStruct):
    """A card on the Project & Board page. Status and due date are worked out from the cards."""

    id: UUID
    business: str
    business_id: UUID
    title: str
    status: m.BoardStatus
    task_count: int
    due_date: dt.date | None
    visibility: m.Visibility


class BoardCreate(CamelizedBaseStruct):
    title: Title
    business: Annotated[str, msgspec.Meta(min_length=1, description="Business id, name or slug")]
    visibility: m.Visibility = m.Visibility.WORKSPACE


class BoardUpdate(CamelizedBaseStruct, omit_defaults=True):
    title: Title | msgspec.UnsetType = msgspec.UNSET
    visibility: m.Visibility | msgspec.UnsetType = msgspec.UNSET


class BoardMember(UserSummary, kw_only=True):
    member_id: UUID
    """The board_member row, for changing access or removing the member."""
    access: m.BoardAccess
    label: str


class MemberAdd(CamelizedBaseStruct):
    user: Annotated[str, msgspec.Meta(min_length=2, description="Email address, full name or user id")]
    access: m.BoardAccess = m.BoardAccess.MEMBER


class MemberUpdate(CamelizedBaseStruct):
    access: m.BoardAccess


# ---------- Lists ----------
class ListCreate(CamelizedBaseStruct):
    title: Title


class ListUpdate(CamelizedBaseStruct, omit_defaults=True):
    title: Title | msgspec.UnsetType = msgspec.UNSET
    position: Annotated[int, msgspec.Meta(ge=0)] | msgspec.UnsetType = msgspec.UNSET


# ---------- Cards ----------
class Task(CamelizedBaseStruct):
    """A card in a list ("Trello Board Card")."""

    id: UUID
    list_id: UUID
    title: str
    cover: str | None
    labels: list[str]
    members: list[UserSummary]
    assignee: UserSummary | None
    """The first member, shown on the card."""
    due_date: dt.date | None
    completed: bool
    has_description: bool
    attachments: int
    checklist_done: int
    checklist_total: int
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, t: m.Task, attachments: int = 0) -> Task:
        members = [UserSummary.from_user(u) for u in t.members]
        return cls(
            id=t.id,
            list_id=t.list_id,
            title=t.title,
            cover=t.cover_url,
            labels=list(t.labels or []),
            members=members,
            assignee=members[0] if members else None,
            due_date=t.due_date,
            completed=t.completed_at is not None,
            has_description=bool(t.description),
            attachments=attachments,
            checklist_done=sum(1 for c in t.checklist if c.done),
            checklist_total=len(t.checklist),
            updated_at=t.updated_at,
        )


class TaskList(CamelizedBaseStruct):
    id: UUID
    title: str
    position: int
    tasks: list[Task]


class BoardDetail(Board):
    lists: list[TaskList]
    members: list[BoardMember]
    can_edit: bool
    """Add lists and cards, edit cards. False for Viewers ("Board Detail (For Employee)")."""
    can_manage: bool
    """Share, change member access and visibility, delete the board."""


class ChecklistItem(CamelizedBaseStruct):
    id: UUID
    text: str
    done: bool


class TaskDetail(Task):
    """The open card ("Component 2" in Figma)."""

    board_id: UUID
    list_title: str
    description: str | None
    checklist: list[ChecklistItem]
    can_edit: bool

    @classmethod
    def build(cls, t: m.Task, list_title: str, attachments: int, can_edit: bool) -> TaskDetail:
        base = Task.from_model(t, attachments)
        return cls(
            **{f: getattr(base, f) for f in Task.__struct_fields__},
            board_id=t.board_id,
            list_title=list_title,
            description=t.description,
            checklist=[ChecklistItem(id=c.id, text=c.text, done=c.done) for c in t.checklist],
            can_edit=can_edit,
        )


class TaskCreate(CamelizedBaseStruct):
    title: CardTitle


class TaskUpdate(CamelizedBaseStruct, omit_defaults=True):
    title: CardTitle | msgspec.UnsetType = msgspec.UNSET
    description: Annotated[str, msgspec.Meta(max_length=20000)] | None | msgspec.UnsetType = msgspec.UNSET
    cover: Url | None | msgspec.UnsetType = msgspec.UNSET
    labels: list[Label] | msgspec.UnsetType = msgspec.UNSET
    due_date: dt.date | None | msgspec.UnsetType = msgspec.UNSET
    completed: bool | msgspec.UnsetType = msgspec.UNSET
    member_ids: list[UUID] | msgspec.UnsetType = msgspec.UNSET
    """Must be members of the board."""


class TaskMove(CamelizedBaseStruct):
    """ "Move Card": another list on this board, or a list on another board."""

    list_id: UUID
    position: Literal["top", "bottom"] | Annotated[int, msgspec.Meta(ge=0)] = "bottom"
    """`top`, `bottom`, or the index to drop the card at (drag and drop), counted without the card itself."""


class ChecklistCreate(CamelizedBaseStruct):
    text: Annotated[str, msgspec.Meta(min_length=1, max_length=500)]


class ChecklistUpdate(CamelizedBaseStruct, omit_defaults=True):
    text: Annotated[str, msgspec.Meta(min_length=1, max_length=500)] | msgspec.UnsetType = msgspec.UNSET
    done: bool | msgspec.UnsetType = msgspec.UNSET


class Comment(CamelizedBaseStruct):
    id: UUID
    author: UserSummary | None
    body: str
    created_at: dt.datetime

    @classmethod
    def from_model(cls, c: m.TaskComment) -> Comment:
        return cls(
            id=c.id,
            author=UserSummary.from_user(c.author) if c.author else None,
            body=c.body,
            created_at=c.created_at,
        )


class CommentCreate(CamelizedBaseStruct):
    body: Annotated[str, msgspec.Meta(min_length=1, max_length=10000)]
