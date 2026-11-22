from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, orm_registry
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._base import BusinessScopedMixin, Money
from app.db.models._enums import ActivityKind, ContactStatus, DealMessageKind, RecordStatus, pg_enum

if TYPE_CHECKING:
    from app.db.models._accounts import User


deal_university = Table(
    "deal_university",
    orm_registry.metadata,
    Column("deal_id", ForeignKey("deal.id", ondelete="CASCADE"), primary_key=True),
    Column("university_id", ForeignKey("university.id", ondelete="CASCADE"), primary_key=True),
)
"""Pipeline detail → "Selected Universities"."""


class Contact(BusinessScopedMixin, UUIDv7AuditBase):
    """Customers and leads. Also the customer on quotations, orders and invoices."""

    __tablename__ = "contact"
    __table_args__ = (
        Index("ix_contact_business_status", "business_id", "status"),
        Index("ix_contact_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str | None] = mapped_column(String(200), default=None)
    email: Mapped[str | None] = mapped_column(CITEXT, default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    customer_type: Mapped[str | None] = mapped_column(String(50), default=None)
    follow_up_date: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[ContactStatus] = mapped_column(
        pg_enum(ContactStatus, "contact_status"), default=ContactStatus.LEAD, server_default=ContactStatus.LEAD.value
    )

    owner: Mapped[User | None] = relationship(lazy="joined")


class PipelineStage(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "pipeline_stage"

    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(20), default="#737373")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Deal(BusinessScopedMixin, UUIDv7AuditBase):
    """A card on the CRM pipeline kanban."""

    __tablename__ = "deal"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating_range"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_positive"),
        Index("ix_deal_stage_position", "stage_id", "position"),
    )

    stage_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_stage.id", ondelete="RESTRICT"))
    contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contact.id", ondelete="SET NULL"), index=True, default=None
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Money, default=None)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    rating: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    expected_date: Mapped[date | None] = mapped_column(Date, default=None)
    scheduled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    position: Mapped[int] = mapped_column(Integer, default=0)
    consultant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultant.id", ondelete="SET NULL"), index=True, default=None
    )
    """"Consultant By" on the pipeline detail."""
    social_media_link: Mapped[str | None] = mapped_column(String(300), default=None)
    opened_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), default=func.now(), server_default=func.now()
    )
    """"Created On": when the opportunity started. Editable, unlike created_at."""

    contact: Mapped[Contact | None] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined")
    """The "Saleperson"."""
    consultant: Mapped[Consultant | None] = relationship(lazy="joined")
    stage: Mapped[PipelineStage] = relationship(lazy="joined", innerjoin=True)
    universities: Mapped[list[University]] = relationship(secondary=deal_university, lazy="selectin")


class DealMessage(UUIDv7AuditBase):
    """A message sent to the contact, or an internal note, on a deal's timeline."""

    __tablename__ = "deal_message"
    __table_args__ = (Index("ix_deal_message_deal_created", "deal_id", "created_at"),)

    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deal.id", ondelete="CASCADE"))
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    kind: Mapped[DealMessageKind] = mapped_column(pg_enum(DealMessageKind, "deal_message_kind"))
    recipient: Mapped[str | None] = mapped_column(String(254), default=None)
    """The "To:" line of a sent message."""
    subject: Mapped[str | None] = mapped_column(String(200), default=None)
    body: Mapped[str] = mapped_column(Text)
    stage_name: Mapped[str | None] = mapped_column(String(100), default=None)
    """Stage the deal was in when this was written ("› Consultation (Stage)")."""

    author: Mapped[User | None] = relationship(lazy="joined")


class DealActivity(UUIDv7AuditBase):
    """A planned follow-up (to-do, call, meeting...) on a deal."""

    __tablename__ = "deal_activity"
    __table_args__ = (Index("ix_deal_activity_deal_due", "deal_id", "due_date"),)

    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deal.id", ondelete="CASCADE"))
    kind: Mapped[ActivityKind] = mapped_column(pg_enum(ActivityKind, "activity_kind"))
    summary: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True, default=None
    )
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    done_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)

    assigned_to: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assigned_to_id])


class University(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "university"
    __table_args__ = (Index("ix_university_business_status", "business_id", "status"),)

    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100), default=None)
    email: Mapped[str | None] = mapped_column(CITEXT, default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    website: Mapped[str | None] = mapped_column(String(300), default=None)
    status: Mapped[RecordStatus] = mapped_column(
        pg_enum(RecordStatus, "record_status"), default=RecordStatus.ACTIVE, server_default=RecordStatus.ACTIVE.value
    )


class Consultant(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "consultant"
    __table_args__ = (Index("ix_consultant_business_status", "business_id", "status"),)

    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100), default=None)
    email: Mapped[str | None] = mapped_column(CITEXT, default=None)
    company_name: Mapped[str | None] = mapped_column(String(200), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    status: Mapped[RecordStatus] = mapped_column(
        pg_enum(RecordStatus, "record_status"), default=RecordStatus.ACTIVE, server_default=RecordStatus.ACTIVE.value
    )
