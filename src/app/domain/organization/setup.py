"""Everything a new company (switcher entry) starts with: roles, pipeline, security settings, admins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db import models as m

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PIPELINE_STAGES = [("New", "#22C55E"), ("Contacted", "#F97316"), ("Qualified", "#D51F2E"), ("Won", "#3B82F6")]

# Every company gets its own copy of these roles. Role -> {module: actions}. "*" means every module.
ALL_ACTIONS = ("create", "read", "update", "delete", "approve")
ROLES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    # Names and order follow Figma "Roles & Permissions". Super Admin is the locked system role.
    "Super Admin": ("Full access to every module and setting.", {"*": ALL_ACTIONS}),
    "Admin": (
        "Manages every module, users and company details.",
        {
            **{module: ALL_ACTIONS for module in ("overview", "crm", "projects", "sales", "invoices", "finance", "hr")},
            "settings": ("create", "read", "update"),
        },
    ),
    "Manager": (
        "Manage teams and approve requests.",
        {
            "overview": ("read",),
            "crm": ("create", "read", "update"),
            "projects": ("create", "read", "update", "delete"),
            "sales": ("create", "read", "update", "approve"),
            "invoices": ("read", "approve"),
            "finance": ("read", "approve"),
            "hr": ("create", "read", "update", "approve"),
            "settings": ("read",),
        },
    ),
    "Accountant": (
        "Invoices, payments and finance.",
        {
            "overview": ("read",),
            "sales": ("read",),
            "invoices": ("create", "read", "update", "approve"),
            "finance": ("create", "read", "update", "approve"),
        },
    ),
    "HR": (
        "Employees, attendance, leave and payroll.",
        {
            "overview": ("read",),
            "projects": ("read",),
            "hr": ("create", "read", "update", "approve"),
        },
    ),
    "Staff": (
        "Day-to-day CRM, sales and project work.",
        {
            "overview": ("read",),
            "crm": ("create", "read", "update"),
            "projects": ("read", "update"),
            "sales": ("create", "read", "update"),
            "invoices": ("create", "read"),
        },
    ),
}
SYSTEM_ROLE = "Super Admin"


async def setup_company(session: AsyncSession, business: m.Business, members: list[m.User] | None = None) -> None:
    """Give a new company its default roles, pipeline stages and security settings.

    Every super admin, and anyone in `members`, joins it with the Super Admin role. Safe to run again.
    """
    existing = {
        r.name for r in (await session.execute(select(m.Role).where(m.Role.business_id == business.id))).scalars()
    }
    for role_name, (description, matrix) in ROLES.items():
        if role_name in existing:
            continue
        modules = [mod.value for mod in m.AppModule] if "*" in matrix else list(matrix)
        role = m.Role(
            business_id=business.id,
            name=role_name,
            description=description,
            is_system=role_name == SYSTEM_ROLE,
            permissions=[
                m.RolePermission(module=m.AppModule(module), action=m.PermissionAction(action))
                for module in modules
                for action in matrix.get("*", matrix.get(module, ()))
            ],
        )
        session.add(role)
    if (
        await session.scalar(select(m.PipelineStage.id).where(m.PipelineStage.business_id == business.id).limit(1))
        is None
    ):
        session.add_all(
            m.PipelineStage(business_id=business.id, name=name, color=color, position=i)
            for i, (name, color) in enumerate(PIPELINE_STAGES)
        )
    if await session.scalar(select(m.SecuritySettings.id).where(m.SecuritySettings.business_id == business.id)) is None:
        session.add(m.SecuritySettings(business_id=business.id))
    await session.flush()

    admin_role = await session.scalar(
        select(m.Role).where(m.Role.business_id == business.id, m.Role.name == SYSTEM_ROLE)
    )
    superusers = list((await session.execute(select(m.User).where(m.User.is_superuser.is_(True)))).scalars().unique())
    for user in {u.id: u for u in [*superusers, *(members or [])]}.values():
        if not await session.get(m.Membership, (user.id, business.id)):
            session.add(
                m.Membership(user_id=user.id, business_id=business.id, role_id=admin_role.id if admin_role else None)
            )
    await session.flush()
