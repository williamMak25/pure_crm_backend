from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._base import BusinessScopedMixin, Money
from app.db.models._enums import OrderStatus, PaymentMethod, QuotationStatus, RecordStatus, pg_enum


class Product(BusinessScopedMixin, UUIDv7AuditBase):
    """Sales → Items: courses, services and merchandise."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("business_id", "code", name="uq_product_business_code"),
        CheckConstraint("unit_price >= 0", name="unit_price_positive"),
        Index("ix_product_business_status", "business_id", "status"),
        Index("ix_product_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    unit_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[RecordStatus] = mapped_column(
        pg_enum(RecordStatus, "record_status"), default=RecordStatus.ACTIVE, server_default=RecordStatus.ACTIVE.value
    )


class Quotation(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "quotation"
    __table_args__ = (
        UniqueConstraint("business_id", "quotation_no", name="uq_quotation_business_no"),
        Index("ix_quotation_business_status", "business_id", "status"),
    )

    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id", ondelete="RESTRICT"), index=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    quotation_no: Mapped[str] = mapped_column(String(50))
    quote_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, default=None)
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[QuotationStatus] = mapped_column(
        pg_enum(QuotationStatus, "quotation_status"),
        default=QuotationStatus.DRAFT,
        server_default=QuotationStatus.DRAFT.value,
    )

    lines: Mapped[list[QuotationLine]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class QuotationLine(UUIDv7AuditBase):
    __tablename__ = "quotation_line"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    quotation_id: Mapped[UUID] = mapped_column(ForeignKey("quotation.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), index=True, default=None
    )
    description: Mapped[str] = mapped_column(String(300))
    """Product name copied at the time of quoting, so renaming a product doesn't rewrite old documents."""
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)


class SalesOrder(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "sales_order"
    __table_args__ = (
        UniqueConstraint("business_id", "order_no", name="uq_sales_order_business_no"),
        Index("ix_sales_order_business_status", "business_id", "status"),
    )

    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id", ondelete="RESTRICT"), index=True)
    quotation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quotation.id", ondelete="SET NULL"), unique=True, default=None
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    order_no: Mapped[str] = mapped_column(String(50))
    order_date: Mapped[date] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    payment_method: Mapped[PaymentMethod | None] = mapped_column(pg_enum(PaymentMethod, "payment_method"), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"), default=OrderStatus.DRAFT, server_default=OrderStatus.DRAFT.value
    )

    lines: Mapped[list[SalesOrderLine]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SalesOrderLine(UUIDv7AuditBase):
    __tablename__ = "sales_order_line"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), index=True, default=None
    )
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)


class DocumentSequence(BusinessScopedMixin, UUIDv7AuditBase):
    """Per-business counters for SO-0001, INV-0001 and so on.

    Lock the row with SELECT ... FOR UPDATE when issuing a number; never use count(*).
    """

    __tablename__ = "document_sequence"
    __table_args__ = (UniqueConstraint("business_id", "doc_type", name="uq_document_sequence"),)

    doc_type: Mapped[str] = mapped_column(String(30))
    prefix: Mapped[str] = mapped_column(String(10))
    next_value: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
