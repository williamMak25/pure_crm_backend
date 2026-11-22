from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, orm_registry
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._base import BusinessScopedMixin
from app.db.models._enums import BoardAccess, BoardStatus, CommentKind, Visibility, pg_enum

if TYPE_CHECKING:
    from app.db.models._accounts import User

task_member = Table(
    "task_member",
    orm_registry.metadata,
    Column("task_id", ForeignKey("task.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True),
)
"""Card members ("Change members"). The first one is shown on the card."""


class Board(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "board"
    __table_args__ = (Index("ix_board_business_status", "business_id", "status"),)

    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[BoardStatus] = mapped_column(
        pg_enum(BoardStatus, "board_status"), default=BoardStatus.PLANNING, server_default=BoardStatus.PLANNING.value
    )
    visibility: Mapped[Visibility] = mapped_column(
        pg_enum(Visibility, "board_visibility"), default=Visibility.WORKSPACE, server_default=Visibility.WORKSPACE.value
    )
    due_date: Mapped[date | None] = mapped_column(Date, default=None)

    lists: Mapped[list[TaskList]] = relationship(
        back_populates="board", lazy="raise", cascade="all, delete-orphan", order_by="TaskList.position"
    )
    members: Mapped[list[BoardMember]] = relationship(lazy="raise", cascade="all, delete-orphan")


class BoardMember(UUIDv7AuditBase):
    __tablename__ = "board_member"
    __table_args__ = (Index("uq_board_member", "board_id", "user_id", unique=True),)

    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), index=True)
    access: Mapped[BoardAccess] = mapped_column(
        pg_enum(BoardAccess, "board_access"), default=BoardAccess.MEMBER, server_default=BoardAccess.MEMBER.value
    )
    label: Mapped[str | None] = mapped_column(String(100), default=None)

    user: Mapped[User] = relationship(lazy="joined", innerjoin=True)


class TaskList(UUIDv7AuditBase):
    __tablename__ = "task_list"
    __table_args__ = (Index("ix_task_list_board_position", "board_id", "position"),)

    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)

    board: Mapped[Board] = relationship(back_populates="lists", lazy="raise")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="task_list", lazy="raise", cascade="all, delete-orphan", order_by="Task.position"
    )


class Task(UUIDv7AuditBase):
    """A card on a board. `board_id` is denormalized so board-wide queries skip the list join."""

    __tablename__ = "task"
    __table_args__ = (Index("ix_task_list_position", "list_id", "position"),)

    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id", ondelete="CASCADE"), index=True)
    list_id: Mapped[UUID] = mapped_column(ForeignKey("task_list.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    cover_url: Mapped[str | None] = mapped_column(String(500), default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)
    labels: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    """"Marked as complete" in the board filter."""
    archived_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    """Archived cards are hidden from the board."""

    task_list: Mapped[TaskList] = relationship(back_populates="tasks", lazy="raise")
    members: Mapped[list[User]] = relationship(secondary=task_member, lazy="selectin", order_by="User.name")
    checklist: Mapped[list[ChecklistItem]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ChecklistItem.position"
    )


class ChecklistItem(UUIDv7AuditBase):
    __tablename__ = "checklist_item"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    position: Mapped[int] = mapped_column(Integer, default=0)


class TaskAttachment(UUIDv7AuditBase):
    __tablename__ = "task_attachment"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    file_url: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)


class TaskComment(UUIDv7AuditBase):
    """Messages and notes in the card detail panel."""

    __tablename__ = "task_comment"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    kind: Mapped[CommentKind] = mapped_column(
        pg_enum(CommentKind, "comment_kind"), default=CommentKind.MESSAGE, server_default=CommentKind.MESSAGE.value
    )
    body: Mapped[str] = mapped_column(Text)

    author: Mapped[User | None] = relationship(lazy="joined")


class TaskActivity(UUIDv7AuditBase):
    __tablename__ = "task_activity"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    action: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
