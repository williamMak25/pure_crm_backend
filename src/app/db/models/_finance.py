from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._base import BusinessScopedMixin, Money
from app.db.models._enums import (
    AccountKind,
    ApprovalStatus,
    EntryType,
    PaymentMethod,
    TransactionStatus,
    pg_enum,
)


class FinanceAccount(BusinessScopedMixin, UUIDv7AuditBase):
    """Where money sits: "KBZ Bank - 0012", "Cash on hand"."""

    __tablename__ = "finance_account"

    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[AccountKind] = mapped_column(pg_enum(AccountKind, "account_kind"), default=AccountKind.BANK)


class FinanceCategory(BusinessScopedMixin, UUIDv7AuditBase):
    """Income and expense categories: Course Fees, Salary, Rent..."""

    __tablename__ = "finance_category"
    __table_args__ = (UniqueConstraint("business_id", "type", "name", name="uq_finance_category"),)

    type: Mapped[EntryType] = mapped_column(pg_enum(EntryType, "entry_type"))
    name: Mapped[str] = mapped_column(String(100))


class IncomeExpense(BusinessScopedMixin, UUIDv7AuditBase):
    """Manual income and expense entries that need approval (Finance → Income & Expense)."""

    __tablename__ = "income_expense"
    __table_args__ = (
        UniqueConstraint("business_id", "ref_no", name="uq_income_expense_business_ref"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_income_expense_business_status", "business_id", "status"),
    )

    category_id: Mapped[UUID] = mapped_column(ForeignKey("finance_category.id", ondelete="RESTRICT"), index=True)
    ref_no: Mapped[str] = mapped_column(String(50))
    type: Mapped[EntryType] = mapped_column(pg_enum(EntryType, "entry_type"))
    entry_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[ApprovalStatus] = mapped_column(
        pg_enum(ApprovalStatus, "approval_status"),
        default=ApprovalStatus.PENDING,
        server_default=ApprovalStatus.PENDING.value,
    )


class FinanceTransaction(BusinessScopedMixin, UUIDv7AuditBase):
    """Money actually moving in or out of an account. Feeds cash flow and dashboard charts.

    Each row comes from at most one source: a payment, an approved income/expense entry or a payroll record.
    """

    __tablename__ = "finance_transaction"
    __table_args__ = (
        UniqueConstraint("business_id", "transaction_no", name="uq_finance_transaction_business_no"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "num_nonnulls(payment_id, income_expense_id, payroll_id) <= 1",
            name="single_source",
        ),
        Index("ix_finance_transaction_business_date", "business_id", "txn_date"),
        Index("ix_finance_transaction_business_status", "business_id", "status"),
    )

    account_id: Mapped[UUID] = mapped_column(ForeignKey("finance_account.id", ondelete="RESTRICT"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("finance_category.id", ondelete="SET NULL"), index=True, default=None
    )
    payment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payment.id", ondelete="SET NULL"), unique=True, default=None
    )
    income_expense_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("income_expense.id", ondelete="SET NULL"), unique=True, default=None
    )
    payroll_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payroll_record.id", ondelete="SET NULL"), unique=True, default=None
    )
    transaction_no: Mapped[str] = mapped_column(String(50))
    type: Mapped[EntryType] = mapped_column(pg_enum(EntryType, "entry_type"))
    method: Mapped[PaymentMethod | None] = mapped_column(pg_enum(PaymentMethod, "payment_method"), default=None)
    txn_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[TransactionStatus] = mapped_column(
        pg_enum(TransactionStatus, "transaction_status"),
        default=TransactionStatus.PENDING,
        server_default=TransactionStatus.PENDING.value,
    )
