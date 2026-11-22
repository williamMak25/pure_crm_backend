"""Login, token refresh, logout and the current user."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from litestar import Controller, Request, Response, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotAuthorizedException
from litestar.params import JSONBody
from litestar.security.jwt import Token

from app.db import models as m
from app.domain.accounts.deps import provide_refresh_token_service, provide_users_service
from app.domain.accounts.guards import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH, auth
from app.domain.accounts.schemas import CurrentUser, LoginRequest
from app.domain.accounts.services import RefreshTokenService, UserService
from app.lib.schema import Message
from app.lib.settings import AppSettings


def to_current_user(user: m.User) -> CurrentUser:
    if user.is_superuser:
        permissions = {module.value: [action.value for action in m.PermissionAction] for module in m.AppModule}
    else:
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for module, action in sorted(user.permission_set):
            grouped[module].append(action)
        permissions = dict(grouped)
    return CurrentUser(
        id=user.id,
        name=user.name,
        role=user.role.name if user.role else ("Admin" if user.is_superuser else "No role"),
        email=user.email,
        avatar=user.avatar_url,
        phones=list(user.phones or []),
        is_superuser=user.is_superuser,
        permissions=permissions,
    )


def _device_info(request: Request[Any, Any, Any]) -> str | None:
    user_agent = request.headers.get("user-agent")
    return user_agent[:255] if user_agent else None


def _session_response(user: m.User, raw_refresh_token: str, settings: AppSettings) -> Response[CurrentUser]:
    """Response that sets the access cookie (short-lived) and refresh cookie (long-lived)."""
    response = auth.login(
        str(user.id),
        response_body=to_current_user(user),
        response_status_code=200,
        token_unique_jwt_id=str(uuid4()),
    )
    # auth.login also echoes the JWT in a response header; drop it so the token never reaches page scripts
    response.headers.pop(auth.auth_header, None)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN,
    )
    return response


class AuthController(Controller):
    """Cookie-based sessions. The frontend calls these with `credentials: 'include'`."""

    path = "/auth"
    tags = ["Auth"]
    dependencies = {
        "users_service": Provide(provide_users_service),
        "refresh_token_service": Provide(provide_refresh_token_service),
    }

    @post("/login", operation_id="Login", exclude_from_auth=True, status_code=200, security=[])
    async def login(
        self,
        request: Request[Any, Any, Any],
        data: JSONBody[LoginRequest],
        users_service: NamedDependency[UserService],
        refresh_token_service: NamedDependency[RefreshTokenService],
        settings: NamedDependency[AppSettings],
    ) -> Response[CurrentUser]:
        """Sign in with email and password. Sets the session cookies and returns the user."""
        user = await users_service.authenticate(data.email.strip(), data.password)
        await users_service.touch_last_active(user)
        raw_token, _ = await refresh_token_service.create_refresh_token(
            user_id=user.id,
            expiration_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
            device_info=_device_info(request),
        )
        return _session_response(user, raw_token, settings)

    @post("/refresh", operation_id="RefreshSession", exclude_from_auth=True, status_code=200, security=[])
    async def refresh(
        self,
        request: Request[Any, Any, Any],
        users_service: NamedDependency[UserService],
        refresh_token_service: NamedDependency[RefreshTokenService],
        settings: NamedDependency[AppSettings],
    ) -> Response[CurrentUser]:
        """Swap the refresh cookie for a new access cookie. Call this when an API request returns 401."""
        if not (raw_token := request.cookies.get(REFRESH_COOKIE_NAME)):
            raise NotAuthorizedException(detail="No session. Sign in again.")
        new_raw_token, new_token = await refresh_token_service.rotate_refresh_token(
            raw_token,
            expiration_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
            device_info=_device_info(request),
        )
        user = await users_service.get_one_or_none(m.User.id == new_token.user_id)
        if user is None or not user.is_active:
            await refresh_token_service.revoke_token_family(new_token.family_id)
            raise NotAuthorizedException(detail="This account is inactive. Ask an administrator to activate it.")
        return _session_response(user, new_raw_token, settings)

    @post("/logout", operation_id="Logout", exclude_from_auth=True, status_code=200, security=[])
    async def logout(
        self,
        request: Request[Any, Any, Any],
        refresh_token_service: NamedDependency[RefreshTokenService],
        settings: NamedDependency[AppSettings],
    ) -> Response[Message]:
        """Revoke this device's session and clear both cookies. Works even if the access cookie expired."""
        if raw_token := request.cookies.get(REFRESH_COOKIE_NAME):
            await refresh_token_service.revoke_raw_token(raw_token)
        response = Response(Message(message="Signed out"), status_code=200)
        response.delete_cookie(ACCESS_COOKIE_NAME, path="/", domain=settings.COOKIE_DOMAIN)
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH, domain=settings.COOKIE_DOMAIN)
        return response


class MeController(Controller):
    path = "/me"
    tags = ["Auth"]

    @get(operation_id="GetMe")
    async def me(self, request: Request[m.User, Token, Any]) -> CurrentUser:
        """The signed-in user, their role and the permissions the UI should respect."""
        return to_current_user(request.user)
