from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._base import BusinessScopedMixin, Money
from app.db.models._enums import (
    ApprovalStatus,
    AttendanceStatus,
    EmployeeStatus,
    PayrollStatus,
    RecordStatus,
    pg_enum,
)


class Department(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "department"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_department_business_name"),)

    head_employee_id: Mapped[UUID | None] = mapped_column(
        # department <-> employee reference each other, so this FK is added after both tables exist
        ForeignKey("employee.id", ondelete="SET NULL", use_alter=True, name="fk_department_head_employee_id"),
        default=None,
    )
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[RecordStatus] = mapped_column(
        pg_enum(RecordStatus, "record_status"), default=RecordStatus.ACTIVE, server_default=RecordStatus.ACTIVE.value
    )


class Employee(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "employee"
    __table_args__ = (
        UniqueConstraint("business_id", "employee_no", name="uq_employee_business_no"),
        CheckConstraint("basic_salary >= 0", name="basic_salary_positive"),
        Index("ix_employee_business_status", "business_id", "status"),
        Index("ix_employee_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"), index=True, default=None
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), unique=True, default=None
    )
    """Set when the employee can also log in."""
    employee_no: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(100), default=None)
    join_date: Mapped[date | None] = mapped_column(Date, default=None)
    basic_salary: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), server_default="0")
    status: Mapped[EmployeeStatus] = mapped_column(
        pg_enum(EmployeeStatus, "employee_status"),
        default=EmployeeStatus.ACTIVE,
        server_default=EmployeeStatus.ACTIVE.value,
    )


class Attendance(UUIDv7AuditBase):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_employee_date"),
        CheckConstraint("check_out IS NULL OR check_in IS NULL OR check_out >= check_in", name="check_out_after_in"),
        Index("ix_attendance_work_date", "work_date"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date)
    check_in: Mapped[time | None] = mapped_column(Time, default=None)
    check_out: Mapped[time | None] = mapped_column(Time, default=None)
    status: Mapped[AttendanceStatus] = mapped_column(
        pg_enum(AttendanceStatus, "attendance_status"),
        default=AttendanceStatus.PRESENT,
        server_default=AttendanceStatus.PRESENT.value,
    )


class LeaveType(BusinessScopedMixin, UUIDv7AuditBase):
    __tablename__ = "leave_type"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_leave_type_business_name"),)

    name: Mapped[str] = mapped_column(String(100))
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    days_per_year: Mapped[int | None] = mapped_column(Integer, default=None)


class LeaveRequest(UUIDv7AuditBase):
    __tablename__ = "leave_request"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="end_after_start"),
        CheckConstraint("days > 0", name="days_positive"),
        Index("ix_leave_request_status", "status"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"), index=True)
    leave_type_id: Mapped[UUID] = mapped_column(ForeignKey("leave_type.id", ondelete="RESTRICT"), index=True)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), default=None)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    """Half days allowed."""
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[ApprovalStatus] = mapped_column(
        pg_enum(ApprovalStatus, "approval_status"),
        default=ApprovalStatus.PENDING,
        server_default=ApprovalStatus.PENDING.value,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class PayrollRecord(UUIDv7AuditBase):
    __tablename__ = "payroll_record"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_month", name="uq_payroll_employee_month"),
        CheckConstraint("extract(day from period_month) = 1", name="period_is_month_start"),
        CheckConstraint("basic >= 0 AND allowance >= 0 AND deduction >= 0", name="amounts_positive"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id", ondelete="RESTRICT"), index=True)
    period_month: Mapped[date] = mapped_column(Date)
    """First day of the month the pay covers."""
    basic: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    allowance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    deduction: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    net_pay: Mapped[Decimal] = mapped_column(Money, Computed("basic + allowance - deduction", persisted=True))
    status: Mapped[PayrollStatus] = mapped_column(
        pg_enum(PayrollStatus, "payroll_status"),
        default=PayrollStatus.PENDING,
        server_default=PayrollStatus.PENDING.value,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
