from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, orm_registry
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._enums import AppModule, PermissionAction, RecordStatus, pg_enum

if TYPE_CHECKING:
    from app.db.models._organization import Business


class Membership(orm_registry.generate_base()):  # type: ignore[misc]
    """A user's place in one company (a `business` row): which companies they can switch to,
    and their role there. Roles are per company, so permissions change with the switcher."""

    __tablename__ = "user_business"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True)
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[UUID | None] = mapped_column(ForeignKey("role.id", ondelete="SET NULL"), index=True, default=None)

    role: Mapped[Role | None] = relationship(lazy="selectin")
    business: Mapped[Business] = relationship(lazy="selectin")


user_business = Membership.__table__


class Role(UUIDv7AuditBase):
    """A role in one company. Each company has its own list and permission matrix."""

    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_role_business_name"),)

    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    """The Super Admin role: full access, can't be edited."""

    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", lazy="selectin", cascade="all, delete-orphan"
    )


class RolePermission(UUIDv7AuditBase):
    """One ticked cell of the permission matrix: role × module × action."""

    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "module", "action", name="uq_role_permission"),
        {"comment": "Rows exist only for granted permissions"},
    )

    role_id: Mapped[UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), index=True)
    module: Mapped[AppModule] = mapped_column(pg_enum(AppModule, "app_module"))
    action: Mapped[PermissionAction] = mapped_column(pg_enum(PermissionAction, "permission_action"))

    role: Mapped[Role] = relationship(back_populates="permissions", lazy="raise")


class User(UUIDv7AuditBase):
    __tablename__ = "user_account"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str | None] = mapped_column(String(255), default=None, deferred=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), default=None)
    phones: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    status: Mapped[RecordStatus] = mapped_column(
        pg_enum(RecordStatus, "record_status"), default=RecordStatus.ACTIVE, server_default=RecordStatus.ACTIVE.value
    )
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    """Bypasses permission checks and company membership. Seeded admin only."""
    last_active_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    default_business_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("business.id", ondelete="SET NULL"), default=None
    )
    """Company the switcher starts on when the browser hasn't remembered one."""

    memberships: Mapped[list[Membership]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    businesses: Mapped[list[Business]] = relationship(
        secondary="user_business", lazy="selectin", viewonly=True, order_by="Business.name"
    )
    """Companies the user belongs to (read-only view of `memberships`)."""
    default_business: Mapped[Business | None] = relationship(lazy="selectin", foreign_keys=[default_business_id])
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", lazy="raise", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status == RecordStatus.ACTIVE

    def membership(self, business_id: UUID | None) -> Membership | None:
        return next((ms for ms in self.memberships if ms.business_id == business_id), None)

    def role_in(self, business_id: UUID | None) -> Role | None:
        ms = self.membership(business_id)
        return ms.role if ms else None

    def role_name(self, business_id: UUID | None) -> str:
        role = self.role_in(business_id)
        return role.name if role else ("Super Admin" if self.is_superuser else "No role")

    def permission_set(self, business_id: UUID | None) -> set[tuple[str, str]]:
        role = self.role_in(business_id)
        return {(p.module.value, p.action.value) for p in role.permissions} if role else set()

    def has_permission(self, module: AppModule | str, action: PermissionAction | str, business_id: UUID | None) -> bool:
        """Permission in one company. Super admins can do everything everywhere."""
        if self.is_superuser:
            return True
        return (str(module), str(action)) in self.permission_set(business_id)

    def can_access_business(self, business_id: UUID) -> bool:
        return self.is_superuser or any(b.id == business_id for b in self.businesses)


class RefreshToken(UUIDv7AuditBase):
    """Refresh tokens with rotation and reuse detection (from the fullstack template).

    Tokens are stored as SHA-256 hashes. Every token from one login shares a `family_id`;
    if a revoked token is presented again, the whole family is revoked.
    """

    __tablename__ = "refresh_token"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    device_info: Mapped[str | None] = mapped_column(String(255), default=None)

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="raise")

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @classmethod
    def create_expires_at(cls, days: int) -> datetime:
        return datetime.now(UTC) + timedelta(days=days)


class ActivityLog(UUIDv7AuditBase):
    """Feeds the dashboard's Recent Activities and audit history."""

    __tablename__ = "activity_log"

    business_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("business.id", ondelete="CASCADE"), index=True, default=None
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True, default=None
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[UUID | None] = mapped_column(default=None)
    action: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
