from __future__ import annotations

from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Company(UUIDv7AuditBase):
    """The group that owns every company in the switcher. Not shown in the UI.

    Company details (email, currency…) live on each `Business`, since every company stands on its own.
    """

    __tablename__ = "company"

    name: Mapped[str] = mapped_column(String(200))

    businesses: Mapped[list[Business]] = relationship(back_populates="company", lazy="raise")


class Branch(UUIDv7AuditBase):
    __tablename__ = "branch"

    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id", ondelete="CASCADE"), index=True)
    """The company this branch (physical location) belongs to."""
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)

    business: Mapped[Business] = relationship(back_populates="branches", lazy="raise")


class Business(UUIDv7AuditBase):
    """A company in the navbar switcher (PURE Education, Anime House, GPM).

    Each one stands on its own: its records, branches, roles, members and settings. The table keeps
    its original name; `business_id` on every operational table is the company it belongs to.
    """

    __tablename__ = "business"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id", ondelete="RESTRICT"), index=True)
    """The group that owns every company in this installation."""
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    address: Mapped[str | None] = mapped_column(Text, default=None)
    currency: Mapped[str] = mapped_column(String(3), default="MMK", server_default="MMK")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Yangon", server_default="Asia/Yangon")
    has_branches: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    company: Mapped[Company] = relationship(back_populates="businesses", lazy="raise")
    branches: Mapped[list[Branch]] = relationship(
        back_populates="business", lazy="selectin", cascade="all, delete-orphan", order_by="Branch.created_at"
    )
    security_settings: Mapped[SecuritySettings | None] = relationship(
        back_populates="business", lazy="selectin", uselist=False, cascade="all, delete-orphan"
    )


class SecuritySettings(UUIDv7AuditBase):
    """Settings → Security, one row per company (switcher entry)."""

    __tablename__ = "security_settings"

    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id", ondelete="CASCADE"), unique=True)
    two_factor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    login_alerts: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    password_expiry_days: Mapped[int | None] = mapped_column(Integer, default=None)

    business: Mapped[Business] = relationship(back_populates="security_settings", lazy="raise")
