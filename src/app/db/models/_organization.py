from __future__ import annotations

from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Company(UUIDv7AuditBase):
    """The organization that owns every business unit (Settings → Company)."""

    __tablename__ = "company"

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    address: Mapped[str | None] = mapped_column(Text, default=None)
    currency: Mapped[str] = mapped_column(String(3), default="MMK", server_default="MMK")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Yangon", server_default="Asia/Yangon")
    has_branches: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    branches: Mapped[list[Branch]] = relationship(back_populates="company", lazy="selectin", cascade="all, delete")
    businesses: Mapped[list[Business]] = relationship(back_populates="company", lazy="raise")
    security_settings: Mapped[SecuritySettings | None] = relationship(
        back_populates="company", lazy="selectin", uselist=False, cascade="all, delete"
    )


class Branch(UUIDv7AuditBase):
    __tablename__ = "branch"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)

    company: Mapped[Company] = relationship(back_populates="branches", lazy="raise")


class Business(UUIDv7AuditBase):
    """A business unit in the switcher: PURE Education, Anime House, GPM."""

    __tablename__ = "business"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)

    company: Mapped[Company] = relationship(back_populates="businesses", lazy="raise")


class SecuritySettings(UUIDv7AuditBase):
    """Settings → Security, one row per company."""

    __tablename__ = "security_settings"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), unique=True)
    two_factor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    login_alerts: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    password_expiry_days: Mapped[int | None] = mapped_column(Integer, default=None)

    company: Mapped[Company] = relationship(back_populates="security_settings", lazy="raise")
