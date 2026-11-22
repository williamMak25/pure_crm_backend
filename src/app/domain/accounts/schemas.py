from __future__ import annotations

from uuid import UUID

import msgspec

from app.db import models as m
from app.lib.schema import CamelizedBaseStruct


class LoginRequest(CamelizedBaseStruct):
    email: str = msgspec.field()
    password: str = msgspec.field()


class CurrentUser(CamelizedBaseStruct):
    """Response of GET /me and POST /auth/login.

    The first six fields are the frontend's `UserSummary`. `permissions` maps a module to its
    allowed actions so the UI can hide buttons the user cannot use.
    """

    id: UUID
    name: str
    role: str
    email: str
    avatar: str | None = None
    phones: list[str] = msgspec.field(default_factory=list)
    is_superuser: bool = False
    permissions: dict[str, list[str]] = msgspec.field(default_factory=dict)


class UserSummary(CamelizedBaseStruct):
    """The frontend's `UserSummary`: avatars and names on cards and tables."""

    id: UUID
    name: str
    role: str
    avatar: str | None = None
    email: str | None = None

    @classmethod
    def from_user(cls, user: m.User) -> UserSummary:
        return cls(
            id=user.id,
            name=user.name,
            role=user.role.name if user.role else ("Admin" if user.is_superuser else "No role"),
            avatar=user.avatar_url,
            email=user.email,
        )
