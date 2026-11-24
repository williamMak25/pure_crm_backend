from __future__ import annotations

from advanced_alchemy.extensions.litestar.providers import create_service_provider
from sqlalchemy.orm import selectinload

from app.db import models as m
from app.domain.accounts.services import RefreshTokenService, RoleService, UserService

provide_users_service = create_service_provider(
    UserService,
    load=[
        selectinload(m.User.memberships).selectinload(m.Membership.role).selectinload(m.Role.permissions),
        selectinload(m.User.businesses),
    ],
    uniquify=True,
    error_messages={"duplicate_key": "A user with this email already exists.", "integrity": "User operation failed."},
)

provide_roles_service = create_service_provider(
    RoleService,
    load=[selectinload(m.Role.permissions)],
    error_messages={"duplicate_key": "A role with this name already exists.", "integrity": "Role operation failed."},
)

provide_refresh_token_service = create_service_provider(RefreshTokenService)
