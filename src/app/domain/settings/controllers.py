"""Settings for the selected company: members, roles and permissions, company details, security.

Each switcher entry is a separate company. Company admins manage their company's members and roles;
account-wide actions (deactivate, reset password) and adding or deleting companies are for super admins.
"""

from __future__ import annotations

import re
import secrets
from typing import Any
from uuid import UUID

from advanced_alchemy.base import orm_registry
from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException, PermissionDeniedException
from litestar.params import FromPath, JSONBody
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select

from app.db import models as m
from app.domain.accounts.deps import provide_refresh_token_service, provide_roles_service, provide_users_service
from app.domain.accounts.guards import requires_permission, requires_superuser
from app.domain.accounts.services import RefreshTokenService, RoleService, UserService
from app.domain.organization.scope import ListQuery, provide_list_query
from app.domain.organization.setup import setup_company
from app.domain.settings.schemas import (
    MODULE_BY_LABEL,
    AppUser,
    AppUserDetail,
    Company,
    CompanyCreate,
    CompanyUpdate,
    ModulePermission,
    Role,
    SecuritySettings,
    UserCreate,
    UserUpdate,
    UserWithPassword,
)
from app.lib import crypt
from app.lib.exceptions import ApplicationClientError, ApplicationConflictError
from app.lib.schema import Paginated

can_read = requires_permission(m.AppModule.SETTINGS, m.PermissionAction.READ)
can_create = requires_permission(m.AppModule.SETTINGS, m.PermissionAction.CREATE)
can_update = requires_permission(m.AppModule.SETTINGS, m.PermissionAction.UPDATE)

ROLE_ORDER = ("Super Admin", "Admin", "Manager", "Accountant", "HR", "Staff")
"""Order of the role list in Figma "Roles & Permissions"."""
SESSION_TIMEOUTS = {"15 minutes": 15, "30 minutes": 30, "1 hour": 60, "8 hours": 480}
PASSWORD_EXPIRY = {"30 days": 30, "60 days": 60, "90 days": 90, "Never": None}
SUPER_ADMIN_ONLY = "Only a super admin can do this: it affects every company this person belongs to"


class SettingsController(Controller):
    path = "/settings"
    tags = ["Settings"]
    dependencies = {
        "users_service": Provide(provide_users_service),
        "roles_service": Provide(provide_roles_service),
        "refresh_token_service": Provide(provide_refresh_token_service),
        "list_query": Provide(provide_list_query, sync_to_thread=False),
    }

    # ---------- members ----------
    @get("/users", operation_id="ListUsers", guards=[can_read])
    async def list_users(
        self,
        users_service: NamedDependency[UserService],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[AppUser]:
        """Members of the selected company. Filter with `search` (name/email) and `status`."""
        filters: list[Any] = [m.User.memberships.any(m.Membership.business_id == company.id)]
        if list_query.search:
            like = "%" + list_query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            filters.append(or_(m.User.name.ilike(like, escape="\\"), m.User.email.ilike(like, escape="\\")))
        if list_query.status:
            try:
                filters.append(m.User.status == m.RecordStatus(list_query.status))
            except ValueError:
                raise ApplicationClientError(f"Unknown status '{list_query.status}'") from None
        session = users_service.repository.session
        total = await session.scalar(select(func.count()).select_from(m.User).where(*filters))
        users = await users_service.get_many(
            *filters,
            statement=select(m.User).order_by(m.User.name).limit(list_query.page_size).offset(list_query.offset),
        )
        return Paginated(
            items=[AppUser.from_user(u, company) for u in users],
            total=total or 0,
            page=list_query.page,
            page_size=list_query.page_size,
        )

    @post("/users", operation_id="AddUser", guards=[can_create])
    async def add_user(
        self,
        users_service: NamedDependency[UserService],
        roles_service: NamedDependency[RoleService],
        company: NamedDependency[m.Business],
        data: JSONBody[UserCreate],
    ) -> UserWithPassword:
        """ "Add User": a new account with a temporary password, or an existing account joining this company."""
        role = await _role(roles_service, company, data.role)
        user = await users_service.get_one_or_none(m.User.email == data.email)
        if user is not None:
            if user.membership(company.id):
                raise ApplicationClientError(f"{user.name} is already a member of {company.name}")
            user.memberships.append(m.Membership(business_id=company.id, role_id=role.id))
            await users_service.update(user)
            user = await _reload(users_service, user.id)
            return UserWithPassword(
                user=AppUserDetail.build(user, company), temporary_password=None, existing_account=True
            )

        password = _temporary_password()
        user = m.User(
            email=data.email,
            name=data.name,
            hashed_password=await crypt.get_password_hash(password),
            phones=[data.phone] if data.phone else [],
            status=data.status,
            default_business_id=company.id,
        )
        user.memberships = [m.Membership(business_id=company.id, role_id=role.id)]
        await users_service.create(user)
        user = await _reload(users_service, user.id)
        return UserWithPassword(user=AppUserDetail.build(user, company), temporary_password=password)

    @get("/users/{user_id:uuid}", operation_id="GetUser", guards=[can_read])
    async def get_user(
        self, users_service: NamedDependency[UserService], company: NamedDependency[m.Business], user_id: FromPath[UUID]
    ) -> AppUserDetail:
        return AppUserDetail.build(await _member(users_service, company, user_id), company)

    @patch("/users/{user_id:uuid}", operation_id="UpdateUser", guards=[can_update])
    async def update_user(
        self,
        users_service: NamedDependency[UserService],
        roles_service: NamedDependency[RoleService],
        refresh_token_service: NamedDependency[RefreshTokenService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        user_id: FromPath[UUID],
        data: JSONBody[UserUpdate],
    ) -> AppUserDetail:
        """Role in this company, profile fields, and (super admins) Active / Inactive."""
        user = await _member(users_service, company, user_id)
        _check_can_edit(current_user, user)
        changes = data.to_dict()
        if "status" in changes:
            if not current_user.is_superuser:
                raise PermissionDeniedException(detail=SUPER_ADMIN_ONLY)
            if changes["status"] != m.RecordStatus.ACTIVE and user.id == current_user.id:
                raise ApplicationClientError("You can't deactivate your own account")
        if "role_id" in changes:
            role = await _role(roles_service, company, str(changes.pop("role_id")))
            user.membership(company.id).role_id = role.id  # type: ignore[union-attr]
        for key, value in changes.items():
            setattr(user, key, value)
        await users_service.update(user)
        user = await _reload(users_service, user.id)
        if user.status != m.RecordStatus.ACTIVE:
            await refresh_token_service.revoke_user_tokens(user.id)
        return AppUserDetail.build(user, company)

    @delete("/users/{user_id:uuid}/membership", operation_id="RemoveFromCompany", guards=[can_update])
    async def remove_from_company(
        self,
        users_service: NamedDependency[UserService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        user_id: FromPath[UUID],
    ) -> None:
        """Take someone out of this company. Their account and other companies are untouched."""
        user = await _member(users_service, company, user_id)
        _check_can_edit(current_user, user)
        if user.id == current_user.id:
            raise ApplicationClientError("You can't remove yourself from the company")
        user.memberships = [ms for ms in user.memberships if ms.business_id != company.id]
        if user.default_business_id == company.id:
            user.default_business_id = None
        await users_service.update(user)

    @post("/users/{user_id:uuid}/reset-password", operation_id="ResetUserPassword", guards=[requires_superuser])
    async def reset_password(
        self,
        users_service: NamedDependency[UserService],
        refresh_token_service: NamedDependency[RefreshTokenService],
        company: NamedDependency[m.Business],
        user_id: FromPath[UUID],
    ) -> UserWithPassword:
        """New temporary password, shown once. The person is signed out everywhere (super admins only)."""
        user = await _member(users_service, company, user_id)
        password = _temporary_password()
        user.hashed_password = await crypt.get_password_hash(password)
        await users_service.update(user)
        user = await _reload(users_service, user.id)
        await refresh_token_service.revoke_user_tokens(user.id)
        return UserWithPassword(user=AppUserDetail.build(user, company), temporary_password=password)

    # ---------- roles ----------
    @get("/roles", operation_id="ListRoles", guards=[can_read])
    async def list_roles(
        self, roles_service: NamedDependency[RoleService], company: NamedDependency[m.Business]
    ) -> list[Role]:
        """The company's roles, with how many of its members have each."""
        session = roles_service.repository.session
        counts = dict(
            (
                await session.execute(
                    select(m.Membership.role_id, func.count())
                    .where(m.Membership.business_id == company.id)
                    .group_by(m.Membership.role_id)
                )
            ).all()
        )
        roles = await roles_service.get_many(m.Role.business_id == company.id)
        roles = sorted(
            roles,
            key=lambda r: (ROLE_ORDER.index(r.name) if r.name in ROLE_ORDER else len(ROLE_ORDER), r.created_at),
        )
        return [
            Role(
                id=r.id, name=r.name, description=r.description or "", users=counts.get(r.id, 0), is_system=r.is_system
            )
            for r in roles
        ]

    @get("/roles/{role_id:uuid}/permissions", operation_id="GetRolePermissions", guards=[can_read])
    async def get_permissions(
        self, roles_service: NamedDependency[RoleService], company: NamedDependency[m.Business], role_id: FromPath[UUID]
    ) -> list[ModulePermission]:
        return ModulePermission.matrix(await _role(roles_service, company, str(role_id)))

    @put("/roles/{role_id:uuid}/permissions", operation_id="SaveRolePermissions", guards=[can_update])
    async def save_permissions(
        self,
        roles_service: NamedDependency[RoleService],
        company: NamedDependency[m.Business],
        role_id: FromPath[UUID],
        data: JSONBody[list[ModulePermission]],
    ) -> list[ModulePermission]:
        """Replace a role's matrix in this company. Applies to its members at their next request."""
        role = await _role(roles_service, company, str(role_id))
        if role.is_system:
            raise ApplicationClientError(f"The {role.name} role always has full access and can't be edited")
        rows: list[tuple[m.AppModule, m.PermissionAction]] = []
        for entry in data:
            module = MODULE_BY_LABEL.get(entry.module)
            if module is None:
                raise ApplicationClientError(f"Unknown module '{entry.module}'")
            for action, allowed in entry.actions.items():
                try:
                    act = m.PermissionAction(action)
                except ValueError:
                    raise ApplicationClientError(f"Unknown action '{action}'") from None
                if allowed:
                    rows.append((module, act))
        # Delete first: re-inserting an unchanged cell would hit the role/module/action unique index.
        session = roles_service.repository.session
        await session.execute(sql_delete(m.RolePermission).where(m.RolePermission.role_id == role.id))
        session.add_all(m.RolePermission(role_id=role.id, module=mod, action=act) for mod, act in rows)
        await session.flush()
        await session.refresh(role, attribute_names=["permissions"])
        return ModulePermission.matrix(role)

    # ---------- company ----------
    @get("/company", operation_id="GetCompany", guards=[can_read])
    async def get_company(
        self, users_service: NamedDependency[UserService], company: NamedDependency[m.Business]
    ) -> Company:
        """The selected company's details and branches."""
        return Company.from_model(company, await _member_count(users_service.repository.session, company.id))

    @patch("/company", operation_id="UpdateCompany", guards=[can_update])
    async def update_company(
        self,
        users_service: NamedDependency[UserService],
        company: NamedDependency[m.Business],
        data: JSONBody[CompanyUpdate],
    ) -> Company:
        """Company Management "Save Changes". Renaming updates the switcher."""
        session = users_service.repository.session
        changes = data.to_dict()
        if "name" in changes:
            clash = await session.scalar(
                select(m.Business.id).where(
                    func.lower(m.Business.name) == changes["name"].strip().lower(), m.Business.id != company.id
                )
            )
            if clash:
                raise ApplicationClientError(f"Another company is already called {changes['name']}")
            changes["name"] = changes["name"].strip()
        if "branches" in changes:
            current = {str(br.id): br for br in company.branches}
            kept = []
            for entry in changes.pop("branches"):
                branch = current.get(entry.id) or m.Branch(business_id=company.id)
                branch.name, branch.address, branch.phone = (
                    entry.name.strip(),
                    entry.address or None,
                    entry.phone or None,
                )
                kept.append(branch)
            company.branches = kept
        for key, value in changes.items():
            setattr(company, key, value)
        await session.flush()
        await session.refresh(company, attribute_names=["branches"])
        return Company.from_model(company, await _member_count(session, company.id))

    @post("/companies", operation_id="CreateCompany", guards=[requires_superuser])
    async def create_company(
        self,
        users_service: NamedDependency[UserService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[CompanyCreate],
    ) -> Company:
        """ "Add Company" (super admins): starts with the default roles, pipeline and security settings."""
        session = users_service.repository.session
        name = data.name.strip()
        if await session.scalar(select(m.Business.id).where(func.lower(m.Business.name) == name.lower())):
            raise ApplicationClientError(f"A company called {name} already exists")
        created = m.Business(company_id=company.company_id, name=name, slug=await _unique_slug(session, name))
        created.branches = []  # a new row has nothing to lazy-load (async can't load on attribute access)
        session.add(created)
        await session.flush()
        await setup_company(session, created, [current_user])
        return Company.from_model(created, await _member_count(session, created.id))

    @delete("/companies/{business_id:uuid}", operation_id="DeleteCompany", guards=[requires_superuser])
    async def delete_company(self, users_service: NamedDependency[UserService], business_id: FromPath[UUID]) -> None:
        """Delete a company (super admins). Refused while it still has records, and for the last company."""
        session = users_service.repository.session
        target = await session.get(m.Business, business_id)
        if target is None:
            raise NotFoundException(detail="Company not found")
        if (await session.scalar(select(func.count()).select_from(m.Business))) <= 1:
            raise ApplicationClientError("You can't delete the last company")
        if records := await _company_records(session, target.id):
            raise ApplicationConflictError(f"{target.name} still has {records}. Move or delete them first.")
        for model in (m.PipelineStage, m.DocumentSequence, m.Role):
            await session.execute(sql_delete(model).where(model.business_id == target.id))
        await session.delete(target)

    # ---------- security ----------
    @get("/security", operation_id="GetSecuritySettings", guards=[can_read])
    async def get_security(
        self, users_service: NamedDependency[UserService], company: NamedDependency[m.Business]
    ) -> SecuritySettings:
        return _security(await _security_row(users_service.repository.session, company))

    @put("/security", operation_id="SaveSecuritySettings", guards=[can_update])
    async def save_security(
        self,
        users_service: NamedDependency[UserService],
        company: NamedDependency[m.Business],
        data: JSONBody[SecuritySettings],
    ) -> SecuritySettings:
        """Stored for the company. Session timeout and password expiry are not enforced yet."""
        if data.session_timeout not in SESSION_TIMEOUTS:
            raise ApplicationClientError(f"Session timeout must be one of: {', '.join(SESSION_TIMEOUTS)}")
        if data.password_expiry not in PASSWORD_EXPIRY:
            raise ApplicationClientError(f"Password expiry must be one of: {', '.join(PASSWORD_EXPIRY)}")
        row = await _security_row(users_service.repository.session, company)
        row.two_factor, row.login_alerts = data.two_factor, data.login_alerts
        row.session_timeout_minutes = SESSION_TIMEOUTS[data.session_timeout]
        row.password_expiry_days = PASSWORD_EXPIRY[data.password_expiry]
        await users_service.repository.session.flush()
        return _security(row)


# ---------- helpers ----------
# Rows in these tables belong to a company but don't count as "its records" when deleting it.
_COMPANY_SETUP_TABLES = {"pipeline_stage", "document_sequence", "branch", "user_business", "role", "security_settings"}


def _temporary_password() -> str:
    return secrets.token_urlsafe(9)


def _check_can_edit(editor: m.User, user: m.User) -> None:
    if user.is_superuser and not editor.is_superuser:
        raise PermissionDeniedException(detail="Only a super admin can change a super admin's account")


async def _member(users: UserService, company: m.Business, user_id: UUID) -> m.User:
    """A member of the company. People outside it look missing."""
    user = await users.get_one_or_none(m.User.id == user_id)
    if user is None or not user.membership(company.id):
        raise NotFoundException(detail="User not found")
    return user


async def _reload(users: UserService, user_id: UUID) -> m.User:
    """Fresh copy with memberships, roles and permissions (saving expires them; async can't lazy-load)."""
    session = users.repository.session
    await session.flush()
    session.expire_all()
    return await users.get(user_id)


async def _role(roles: RoleService, company: m.Business, ref: str) -> m.Role:
    try:
        condition: Any = m.Role.id == UUID(ref)
    except ValueError:
        condition = func.lower(m.Role.name) == ref.strip().lower()
    role = await roles.get_one_or_none(condition, m.Role.business_id == company.id)
    if role is None:
        raise ApplicationClientError(f"{company.name} has no role '{ref}'")
    return role


async def _member_count(session: Any, business_id: UUID) -> int:
    return await session.scalar(select(func.count()).where(m.Membership.business_id == business_id)) or 0


async def _company_records(session: Any, business_id: UUID) -> str:
    """ "12 contacts, 3 boards" for every company-scoped table that still has rows for the company."""
    found = []
    for table in orm_registry.metadata.sorted_tables:
        if "business_id" not in table.c or table.name in _COMPANY_SETUP_TABLES:
            continue
        count = await session.scalar(select(func.count()).select_from(table).where(table.c.business_id == business_id))
        if count:
            found.append(f"{count} {table.name.replace('_', ' ')}{'' if count == 1 else 's'}")
    return ", ".join(found)


async def _unique_slug(session: Any, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"
    slug, n = base, 2
    while await session.scalar(select(m.Business.id).where(m.Business.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


async def _security_row(session: Any, company: m.Business) -> m.SecuritySettings:
    if company.security_settings is None:
        company.security_settings = m.SecuritySettings(business_id=company.id)
        await session.flush()
    return company.security_settings


def _security(row: m.SecuritySettings) -> SecuritySettings:
    timeout = next((k for k, v in SESSION_TIMEOUTS.items() if v == row.session_timeout_minutes), "30 minutes")
    expiry = next((k for k, v in PASSWORD_EXPIRY.items() if v == row.password_expiry_days), "Never")
    return SecuritySettings(
        two_factor=row.two_factor, login_alerts=row.login_alerts, session_timeout=timeout, password_expiry=expiry
    )
