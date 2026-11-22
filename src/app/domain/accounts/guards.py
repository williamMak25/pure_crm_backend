"""Authentication (JWT in an httpOnly cookie) and authorization guards."""

from __future__ import annotations

from contextlib import aclosing
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from litestar.exceptions import PermissionDeniedException
from litestar.security.jwt import JWTCookieAuth, Token

from app.config import alchemy
from app.db import models as m
from app.domain.accounts.deps import provide_users_service
from app.lib.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.connection import ASGIConnection, Request
    from litestar.handlers.base import BaseRouteHandler

settings = get_settings()
ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = f"{settings.app.API_PREFIX}/auth"
"""The refresh cookie is only sent to /auth/*, never to ordinary API calls."""


async def current_user_from_token(token: Token, connection: ASGIConnection[Any, Any, Any, Any]) -> m.User | None:
    """Load the user named in the JWT. Returning None makes the request a 401."""
    try:
        user_id = UUID(token.sub)
    except ValueError:
        return None
    db_session = alchemy.provide_session(connection.app.state, connection.scope)
    async with aclosing(provide_users_service(db_session)) as services:
        users_service = await anext(services)
        user = await users_service.get_one_or_none(m.User.id == user_id)
    return user if user and user.is_active else None


def provide_user(request: Request[m.User, Token, Any]) -> m.User:
    return request.user


def requires_superuser(connection: ASGIConnection[Any, m.User, Token, Any], _: BaseRouteHandler) -> None:
    if not connection.user.is_superuser:
        raise PermissionDeniedException(detail="Only administrators can do this")


def requires_permission(
    module: m.AppModule, action: m.PermissionAction
) -> Callable[[ASGIConnection[Any, m.User, Token, Any], BaseRouteHandler], None]:
    """Guard factory for the role permission matrix.

    Example: ``@get(guards=[requires_permission(m.AppModule.CRM, m.PermissionAction.READ)])``
    """

    def guard(connection: ASGIConnection[Any, m.User, Token, Any], _: BaseRouteHandler) -> None:
        if not connection.user.has_permission(module, action):
            raise PermissionDeniedException(detail=f"Your role cannot {action.value} in {module.value}")

    return guard


auth = JWTCookieAuth[m.User](
    retrieve_user_handler=current_user_from_token,
    token_secret=settings.app.SECRET_KEY,
    algorithm=settings.app.JWT_ENCRYPTION_ALGORITHM,
    key=ACCESS_COOKIE_NAME,
    default_token_expiration=timedelta(minutes=settings.app.ACCESS_TOKEN_EXPIRE_MINUTES),
    secure=settings.app.COOKIE_SECURE,
    domain=settings.app.COOKIE_DOMAIN,
    samesite="lax",
    # login/refresh/logout opt out per handler with exclude_from_auth=True
    exclude=["^/health", "^/schema"],
    exclude_http_methods=["OPTIONS"],
)
