"""Settings: users, roles and permissions, company and security. Names match the frontend's types."""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

import msgspec

from app.db import models as m
from app.lib.schema import CamelizedBaseStruct

MODULE_LABELS: dict[m.AppModule, str] = {
    m.AppModule.OVERVIEW: "Overview",
    m.AppModule.CRM: "CRM & Contacts",
    m.AppModule.PROJECTS: "Project & Board",
    m.AppModule.SALES: "Sales",
    m.AppModule.INVOICES: "Invoices",
    m.AppModule.FINANCE: "Finance",
    m.AppModule.HR: "HR & Payroll",
    m.AppModule.SETTINGS: "Setting",
}
"""Row labels of the permission matrix in the UI."""
MODULE_BY_LABEL = {label: module for module, label in MODULE_LABELS.items()}

Name = Annotated[str, msgspec.Meta(min_length=1, max_length=200)]
Email = Annotated[str, msgspec.Meta(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)]
Phone = Annotated[str, msgspec.Meta(max_length=50)]


# ---------- roles ----------
class Role(CamelizedBaseStruct):
    id: UUID
    name: str
    description: str
    users: int
    is_system: bool
    """The built-in Admin role: full access, can't be edited."""


class ModulePermission(CamelizedBaseStruct):
    module: str
    actions: dict[str, bool]

    @classmethod
    def matrix(cls, role: m.Role | None) -> list[ModulePermission]:
        granted = {(p.module, p.action) for p in role.permissions} if role else set()
        return [
            cls(module=label, actions={a.value: (module, a) in granted for a in m.PermissionAction})
            for module, label in MODULE_LABELS.items()
        ]


# ---------- users ----------
class AppUser(CamelizedBaseStruct):
    """A member of the selected company (User Management)."""

    id: UUID
    name: str
    email: str
    phones: list[str]
    role: str
    """Role in the selected company."""
    role_id: UUID | None
    companies: list[str]
    """Every company the person belongs to."""
    avatar: str | None
    status: m.RecordStatus
    last_active: dt.datetime | None
    is_superuser: bool

    @classmethod
    def from_user(cls, u: m.User, company: m.Business) -> AppUser:
        ms = u.membership(company.id)
        return cls(
            id=u.id,
            name=u.name,
            email=u.email,
            phones=list(u.phones or []),
            role=u.role_name(company.id),
            role_id=ms.role_id if ms else None,
            companies=[b.name for b in u.businesses],
            avatar=u.avatar_url,
            status=u.status,
            last_active=u.last_active_at,
            is_superuser=u.is_superuser,
        )


class AppUserDetail(AppUser):
    permissions: list[ModulePermission]
    """What the person's role allows in the selected company, module by module."""

    @classmethod
    def build(cls, u: m.User, company: m.Business) -> AppUserDetail:
        base = AppUser.from_user(u, company)
        return cls(
            **{f: getattr(base, f) for f in AppUser.__struct_fields__},
            permissions=ModulePermission.matrix(u.role_in(company.id)),
        )


class UserCreate(CamelizedBaseStruct):
    """ "Add User" to the selected company.

    A new email creates an account with a temporary password (shown once). An existing email adds that
    person to this company instead; they keep their password.
    """

    name: Name
    email: Email
    role: Annotated[str, msgspec.Meta(min_length=1, description="Role id or name in this company")]
    phone: Phone | None = None
    status: m.RecordStatus = m.RecordStatus.ACTIVE


class UserUpdate(CamelizedBaseStruct, omit_defaults=True):
    name: Name | msgspec.UnsetType = msgspec.UNSET
    phones: list[Phone] | msgspec.UnsetType = msgspec.UNSET
    role_id: UUID | msgspec.UnsetType = msgspec.UNSET
    """Role in the selected company."""
    status: m.RecordStatus | msgspec.UnsetType = msgspec.UNSET
    """Account-wide (every company): super admins only."""


class UserWithPassword(CamelizedBaseStruct):
    """After "Add User" or "Reset password". There is no email service yet, so the password is shown once."""

    user: AppUserDetail
    temporary_password: str | None
    """None when an existing account was added to this company."""
    existing_account: bool = False


# ---------- company ----------
class Branch(CamelizedBaseStruct):
    id: str
    """Existing branch id, or any placeholder for a new branch."""
    name: Name
    address: str = ""
    phone: str = ""


class Company(CamelizedBaseStruct):
    """The selected company (a switcher entry): details and branches."""

    id: UUID
    name: str
    slug: str
    email: str
    phone: str
    address: str
    currency: str
    timezone: str
    has_branches: bool
    branches: list[Branch]
    members: int

    @classmethod
    def from_model(cls, b: m.Business, members: int) -> Company:
        return cls(
            id=b.id,
            name=b.name,
            slug=b.slug,
            email=b.email or "",
            phone=b.phone or "",
            address=b.address or "",
            currency=b.currency,
            timezone=b.timezone,
            has_branches=b.has_branches,
            branches=[
                Branch(id=str(br.id), name=br.name, address=br.address or "", phone=br.phone or "") for br in b.branches
            ],
            members=members,
        )


class CompanyUpdate(CamelizedBaseStruct, omit_defaults=True):
    """Company Management "Save Changes". `branches` is the full list: missing ones are removed."""

    name: Name | msgspec.UnsetType = msgspec.UNSET
    email: Email | msgspec.UnsetType = msgspec.UNSET
    phone: Phone | msgspec.UnsetType = msgspec.UNSET
    address: Annotated[str, msgspec.Meta(max_length=1000)] | msgspec.UnsetType = msgspec.UNSET
    currency: Annotated[str, msgspec.Meta(min_length=3, max_length=3)] | msgspec.UnsetType = msgspec.UNSET
    timezone: Annotated[str, msgspec.Meta(min_length=1, max_length=64)] | msgspec.UnsetType = msgspec.UNSET
    has_branches: bool | msgspec.UnsetType = msgspec.UNSET
    branches: list[Branch] | msgspec.UnsetType = msgspec.UNSET


class CompanyCreate(CamelizedBaseStruct):
    """ "Add Company" (super admins). It starts with the default roles and pipeline."""

    name: Name


# ---------- security ----------
class SecuritySettings(CamelizedBaseStruct):
    """Company-wide sign-in settings. Durations are the labels the form shows."""

    two_factor: bool
    login_alerts: bool
    session_timeout: str
    password_expiry: str


class PasswordChange(CamelizedBaseStruct):
    current_password: str
    new_password: Annotated[str, msgspec.Meta(min_length=8, max_length=128)]
