"""`app seed` and `app users ...` commands."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BUSINESSES = [("PURE Education", "pure-education"), ("Anime House", "anime-house"), ("GPM", "gpm")]


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
    from app.domain.organization.setup import setup_company
    from app.lib import crypt

    if admin_email:
        existing = (await session.execute(select(m.User).where(m.User.email == admin_email))).scalar_one_or_none()
        if existing is not None:
            click.echo(f"Admin {admin_email} already exists, left unchanged")
        elif not admin_password:
            msg = "--admin-password is required when creating the admin user"
            raise click.UsageError(msg)
        else:
            session.add(
                m.User(
                    email=admin_email,
                    name=admin_name,
                    hashed_password=await crypt.get_password_hash(admin_password),
                    is_superuser=True,
                )
            )
            await session.flush()
            click.echo(f"Created admin {admin_email}")

    group = (await session.execute(select(m.Company).limit(1))).scalar_one_or_none()
    if group is None:
        group = m.Company(name="PURE ERP")
        session.add(group)
        await session.flush()

    for name, slug in BUSINESSES:
        business = (await session.execute(select(m.Business).where(m.Business.slug == slug))).scalar_one_or_none()
        if business is None:
            business = m.Business(company_id=group.id, name=name, slug=slug)
            session.add(business)
            await session.flush()
            click.echo(f"Created company {name}")
        # Roles, pipeline and security settings, with every super admin as a member.
        await setup_company(session, business)


@click.command(
    name="seed", help="Create the companies with their default roles and pipeline, and (optionally) a super admin."
)
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
    from app.domain.organization.setup import ROLES
    from app.lib import crypt

    businesses = list((await session.execute(select(m.Business).where(m.Business.slug.in_(business_slugs)))).scalars())
    if missing := set(business_slugs) - {b.slug for b in businesses}:
        msg = f"Unknown company slug(s): {', '.join(sorted(missing))}"
        raise click.UsageError(msg)
    user = m.User(email=email, name=name, hashed_password=await crypt.get_password_hash(password))
    for business in businesses:
        role = await session.scalar(select(m.Role).where(m.Role.business_id == business.id, m.Role.name == role_name))
        if role is None:
            msg = f"{business.name} has no role '{role_name}'. Run `app seed` first or pick one of: {', '.join(ROLES)}"
            raise click.UsageError(msg)
        user.memberships.append(m.Membership(business_id=business.id, role_id=role.id))
    session.add(user)
    click.echo(f"Created {email} as {role_name} in {', '.join(b.name for b in businesses) or 'no company'}")


@users_group.command(name="create", help="Create a user with a role in one or more companies.")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--role", "role_name", default="Staff", show_default=True)
@click.option(
    "--business",
    "business_slugs",
    multiple=True,
    help="Company slug, repeatable: pure-education, anime-house, gpm",
)
def create_user(email: str, name: str, password: str, role_name: str, business_slugs: tuple[str, ...]) -> None:
    _run(_create_user, email, name, password, role_name, business_slugs)
