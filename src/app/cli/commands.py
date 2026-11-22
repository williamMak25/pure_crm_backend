"""`app seed` and `app users ...` commands."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BUSINESSES = [("PURE Education", "pure-education"), ("Anime House", "anime-house"), ("GPM", "gpm")]
PIPELINE_STAGES = [("New", "#22C55E"), ("Contacted", "#F97316"), ("Qualified", "#D51F2E"), ("Won", "#3B82F6")]

# Role -> {module: actions}. "*" means every module.
ALL_ACTIONS = ("create", "read", "update", "delete", "approve")
ROLES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "Admin": ("Full access to every module", {"*": ALL_ACTIONS}),
    "Manager": (
        "Manage teams and approve requests",
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
    "Finance": (
        "Invoices, payments and finance",
        {
            "overview": ("read",),
            "sales": ("read",),
            "invoices": ("create", "read", "update", "approve"),
            "finance": ("create", "read", "update", "approve"),
        },
    ),
    "Sales": (
        "CRM and sales orders",
        {
            "overview": ("read",),
            "crm": ("create", "read", "update"),
            "projects": ("read", "update"),
            "sales": ("create", "read", "update"),
            "invoices": ("create", "read"),
        },
    ),
    "HR": (
        "Employees, attendance and payroll",
        {
            "overview": ("read",),
            "projects": ("read",),
            "hr": ("create", "read", "update", "approve"),
        },
    ),
    "Viewer": (
        "Read-only access",
        {module: ("read",) for module in ("overview", "crm", "projects", "sales", "invoices", "finance", "hr")},
    ),
}


def _run(coro_fn, *args):  # type: ignore[no-untyped-def]
    from app.config import alchemy

    async def runner() -> None:
        async with alchemy.get_session() as session:
            await coro_fn(session, *args)
            await session.commit()
        await alchemy.get_engine().dispose()

    asyncio.run(runner())


async def _seed(session: AsyncSession, admin_email: str | None, admin_password: str | None, admin_name: str) -> None:
    from sqlalchemy import select

    from app.db import models as m
    from app.lib import crypt

    company = (await session.execute(select(m.Company).limit(1))).scalar_one_or_none()
    if company is None:
        company = m.Company(name="PURE Education", currency="MMK", timezone="Asia/Yangon")
        session.add(company)
        await session.flush()
        session.add(m.SecuritySettings(company_id=company.id))
        click.echo(f"Created company {company.name}")

    for name, slug in BUSINESSES:
        business = (await session.execute(select(m.Business).where(m.Business.slug == slug))).scalar_one_or_none()
        if business is None:
            business = m.Business(company_id=company.id, name=name, slug=slug)
            session.add(business)
            await session.flush()
            click.echo(f"Created business {name}")
        has_stages = await session.scalar(select(m.PipelineStage.id).where(m.PipelineStage.business_id == business.id))
        if has_stages is None:
            for position, (stage, color) in enumerate(PIPELINE_STAGES):
                session.add(m.PipelineStage(business_id=business.id, name=stage, color=color, position=position))
            click.echo(f"Created default pipeline for {name}")

    for role_name, (description, matrix) in ROLES.items():
        role = (await session.execute(select(m.Role).where(m.Role.name == role_name))).scalar_one_or_none()
        if role is None:
            role = m.Role(name=role_name, description=description, is_system=role_name == "Admin")
            session.add(role)
            await session.flush()
            modules = [mod.value for mod in m.AppModule] if "*" in matrix else list(matrix)
            for module in modules:
                for action in matrix.get("*", matrix.get(module, ())):
                    session.add(
                        m.RolePermission(role_id=role.id, module=m.AppModule(module), action=m.PermissionAction(action))
                    )
            click.echo(f"Created role {role_name}")
    await session.flush()

    if admin_email:
        existing = (await session.execute(select(m.User).where(m.User.email == admin_email))).scalar_one_or_none()
        if existing is not None:
            click.echo(f"Admin {admin_email} already exists, left unchanged")
            return
        if not admin_password:
            msg = "--admin-password is required when creating the admin user"
            raise click.UsageError(msg)
        admin_role = (await session.execute(select(m.Role).where(m.Role.name == "Admin"))).scalar_one()
        session.add(
            m.User(
                email=admin_email,
                name=admin_name,
                hashed_password=await crypt.get_password_hash(admin_password),
                is_superuser=True,
                role_id=admin_role.id,
            )
        )
        click.echo(f"Created admin {admin_email}")


@click.command(name="seed", help="Create the company, business units, default roles and (optionally) an admin user.")
@click.option("--admin-email", envvar="SEED_ADMIN_EMAIL", default=None, help="Admin email. Env: SEED_ADMIN_EMAIL")
@click.option(
    "--admin-password", envvar="SEED_ADMIN_PASSWORD", default=None, help="Admin password. Env: SEED_ADMIN_PASSWORD"
)
@click.option("--admin-name", envvar="SEED_ADMIN_NAME", default="Administrator", show_default=True)
def seed_command(admin_email: str | None, admin_password: str | None, admin_name: str) -> None:
    _run(_seed, admin_email, admin_password, admin_name)
    click.echo("Seed complete")


@click.group(name="users", invoke_without_command=False, help="Manage application users.")
def users_group() -> None: ...


async def _create_user(
    session: AsyncSession, email: str, name: str, password: str, role_name: str, business_slugs: tuple[str, ...]
) -> None:
    from sqlalchemy import select

    from app.db import models as m
    from app.lib import crypt

    role = (await session.execute(select(m.Role).where(m.Role.name == role_name))).scalar_one_or_none()
    if role is None:
        msg = f"Role '{role_name}' not found. Run `app seed` first or pick one of: {', '.join(ROLES)}"
        raise click.UsageError(msg)
    businesses = list((await session.execute(select(m.Business).where(m.Business.slug.in_(business_slugs)))).scalars())
    if missing := set(business_slugs) - {b.slug for b in businesses}:
        msg = f"Unknown business slug(s): {', '.join(sorted(missing))}"
        raise click.UsageError(msg)
    user = m.User(
        email=email,
        name=name,
        hashed_password=await crypt.get_password_hash(password),
        role_id=role.id,
    )
    user.businesses = businesses
    session.add(user)
    click.echo(f"Created {email} with role {role_name} in {', '.join(b.name for b in businesses) or 'no business'}")


@users_group.command(name="create", help="Create a user with a role and business access.")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--role", "role_name", default="Viewer", show_default=True)
@click.option(
    "--business",
    "business_slugs",
    multiple=True,
    help="Business slug, repeatable: pure-education, anime-house, gpm",
)
def create_user(email: str, name: str, password: str, role_name: str, business_slugs: tuple[str, ...]) -> None:
    _run(_create_user, email, name, password, role_name, business_slugs)
