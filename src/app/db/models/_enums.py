"""Postgres enum types.

The frontend uses one big `Status` union; the database splits it per table so a value
that belongs to another module (an invoice that is "Present") cannot be stored.
Values are the exact strings the frontend displays.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache

from sqlalchemy import Enum


@cache
def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Native Postgres enum that stores the enum *values* (e.g. "In Progress"), not member names.

    Cached so tables sharing a type (record_status, payment_method...) use one Enum object.
    """
    return Enum(enum_cls, name=name, values_callable=lambda e: [member.value for member in e], validate_strings=True)


class RecordStatus(StrEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    PENDING = "Pending"


class ContactStatus(StrEnum):
    """Status of a student contact (Contact List). The database type still holds an unused "Lead" value."""

    ACTIVE = "Active"
    INACTIVE = "Inactive"
    ARCHIVED = "Archived"


class ContactKind(StrEnum):
    """Contact List (students) or the Leads tab."""

    STUDENT = "student"
    LEAD = "lead"


class LeadStatus(StrEnum):
    """Leads tab. Setting "New" sends the lead to the pipeline, after which it reads "In Pipeline"."""

    OPEN = "Open"
    CONTACTED = "Contacted"
    NEW = "New"
    IN_PIPELINE = "In Pipeline"
    LOST = "Lost"


class DealMessageKind(StrEnum):
    """Pipeline detail → "Send Message" (sent to the contact) or "Long Note" (internal)."""

    MESSAGE = "message"
    NOTE = "note"


class ActivityKind(StrEnum):
    """Pipeline detail → Activity type buttons."""

    TODO = "To Do"
    EMAIL = "Email"
    CALL = "Call"
    MEETING = "Meeting"
    DOCUMENT = "Document"
    SIGNATURE = "Signature"


class AppModule(StrEnum):
    """Modules in the role permission matrix (Settings → Roles)."""

    OVERVIEW = "overview"
    CRM = "crm"
    PROJECTS = "projects"
    SALES = "sales"
    INVOICES = "invoices"
    FINANCE = "finance"
    HR = "hr"
    SETTINGS = "settings"


class PermissionAction(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"


class BoardStatus(StrEnum):
    PLANNING = "Planning"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"


class Visibility(StrEnum):
    PRIVATE = "private"
    WORKSPACE = "workspace"
    PUBLIC = "public"


class BoardAccess(StrEnum):
    ADMIN = "Admin"
    MEMBER = "Member"
    VIEWER = "Viewer"


class CommentKind(StrEnum):
    MESSAGE = "message"
    NOTE = "note"


class QuotationStatus(StrEnum):
    DRAFT = "Draft"
    SENT = "Sent"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class OrderStatus(StrEnum):
    DRAFT = "Draft"
    PENDING = "Pending"
    UNPAID = "Unpaid"
    PAID = "Paid"


class InvoiceStatus(StrEnum):
    DRAFT = "Draft"
    SENT = "Sent"
    PENDING = "Pending"
    UNPAID = "Unpaid"
    PAID = "Paid"
    OVERDUE = "Overdue"


class PaymentStatus(StrEnum):
    PENDING = "Pending"
    PAID = "Paid"
    REJECTED = "Rejected"


class PaymentMethod(StrEnum):
    CASH = "Cash"
    KBZ_PAY = "KBZ Pay"
    AYA_PAY = "AYA Pay"
    WAVE_PAY = "Wave Pay"
    BANK_TRANSFER = "Bank Transfer"
    CARD = "Card"


class ApprovalStatus(StrEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class EntryType(StrEnum):
    INCOME = "Income"
    EXPENSE = "Expense"


class AccountKind(StrEnum):
    BANK = "bank"
    CASH = "cash"
    WALLET = "wallet"


class TransactionStatus(StrEnum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    REJECTED = "Rejected"


class EmployeeStatus(StrEnum):
    ACTIVE = "Active"
    ON_LEAVE = "On Leave"
    INACTIVE = "Inactive"


class AttendanceStatus(StrEnum):
    PRESENT = "Present"
    LATE = "Late"
    ABSENT = "Absent"
    ON_LEAVE = "On Leave"


class PayrollStatus(StrEnum):
    PENDING = "Pending"
    PAID = "Paid"
