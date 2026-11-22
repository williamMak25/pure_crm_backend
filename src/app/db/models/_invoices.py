from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._base import BusinessScopedMixin, Money
from app.db.models._enums import InvoiceStatus, PaymentMethod, PaymentStatus, pg_enum


class Invoice(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "invoice"
    __table_args__ = (
        UniqueConstraint("business_id", "invoice_no", name="uq_invoice_business_no"),
        CheckConstraint("amount >= 0", name="amount_positive"),
        CheckConstraint("paid_amount >= 0 AND paid_amount <= amount", name="paid_within_amount"),
        Index("ix_invoice_business_status", "business_id", "status"),
        Index("ix_invoice_status_due", "status", "due_date"),
    )

    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sales_order.id", ondelete="SET NULL"), index=True, default=None
    )
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id", ondelete="RESTRICT"), index=True)
    invoice_no: Mapped[str] = mapped_column(String(50))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), server_default="0")
    status: Mapped[InvoiceStatus] = mapped_column(
        pg_enum(InvoiceStatus, "invoice_status"),
        default=InvoiceStatus.PENDING,
        server_default=InvoiceStatus.PENDING.value,
    )


class Payment(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "payment"
    __table_args__ = (
        UniqueConstraint("business_id", "payment_no", name="uq_payment_business_no"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payment_business_status", "business_id", "status"),
    )

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoice.id", ondelete="RESTRICT"), index=True)
    payment_no: Mapped[str] = mapped_column(String(50))
    method: Mapped[PaymentMethod] = mapped_column(pg_enum(PaymentMethod, "payment_method"))
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    external_ref: Mapped[str | None] = mapped_column(String(100), default=None)
    """Bank or wallet transaction id shown on the order detail page."""
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, "payment_status"),
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )


class InvoiceEvent(UUIDv7AuditBase):
    """One row per invoice change. Backs Invoices → History."""

    __tablename__ = "invoice_event"

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoice.id", ondelete="CASCADE"), index=True)
    performed_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    action: Mapped[str] = mapped_column(String(50))
    amount: Mapped[Decimal | None] = mapped_column(Money, default=None)
    status: Mapped[InvoiceStatus] = mapped_column(pg_enum(InvoiceStatus, "invoice_status"))
