"""Shared column types and mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

if TYPE_CHECKING:
    from app.db.models._organization import Business

Money = Numeric(14, 2)
"""All money columns. Never use float for amounts."""


class BusinessScopedMixin:
    """Adds `business_id` to operational tables.

    The app switches between business units (PURE Education, Anime House, GPM), so every
    list query filters on this column.
    """

    @declared_attr
    def business_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(ForeignKey("business.id", ondelete="RESTRICT"), nullable=False, index=True)

    @declared_attr
    def business(cls) -> Mapped[Business]:  # noqa: N805
        # Every table shows the business name, and there are only a handful of businesses.
        return relationship("Business", lazy="joined", innerjoin=True)
