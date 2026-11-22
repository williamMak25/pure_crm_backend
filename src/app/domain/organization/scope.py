"""Business-unit scoping and list parameters shared by every module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from litestar.exceptions import NotFoundException, PermissionDeniedException
from litestar.params import FromQuery, QueryParameter
from sqlalchemy import func, or_, select

from app.db import models as m
from app.lib.exceptions import ApplicationClientError

if TYPE_CHECKING:
    from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute


@dataclass
class ListQuery:
    """`ListParams` sent by the frontend's tables."""

    page: int
    page_size: int
    search: str | None
    business: str | None
    status: str | None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def provide_list_query(
    page: Annotated[int, QueryParameter(ge=1)] = 1,
    page_size: Annotated[int, QueryParameter(name="pageSize", ge=1, le=100)] = 10,
    search: Annotated[str | None, QueryParameter(max_length=100)] = None,
    business: Annotated[str | None, QueryParameter(description="Business id, name or slug")] = None,
    status: FromQuery[str | None] = None,
) -> ListQuery:
    return ListQuery(
        page=page,
        page_size=page_size,
        search=(search or "").strip() or None,
        business=business or None,
        status=status or None,
    )


async def resolve_business(db_session: AsyncSession, user: m.User, ref: str) -> m.Business:
    """Find a business by id, name or slug, and check the user may work in it.

    The frontend sends the display name ("PURE Education") from its switcher and forms.
    """
    try:
        condition: ColumnElement[bool] = m.Business.id == UUID(ref)
    except ValueError:
        condition = or_(func.lower(m.Business.name) == ref.strip().lower(), m.Business.slug == ref.strip().lower())
    business = (await db_session.execute(select(m.Business).where(condition))).scalar_one_or_none()
    if business is None:
        raise ApplicationClientError(f"Unknown business '{ref}'")
    if not user.can_access_business(business.id):
        raise PermissionDeniedException(detail=f"You don't have access to {business.name}")
    return business


def business_filter(user: m.User, column: InstrumentedAttribute[UUID]) -> ColumnElement[bool] | None:
    """Limit rows to the user's businesses. Administrators see every business."""
    if user.is_superuser:
        return None
    return column.in_([b.id for b in user.businesses])


async def resolve_user(db_session: AsyncSession, ref: str, business_id: UUID) -> m.User:
    """Find an active user by id or name (case-insensitive) who works in the business.

    Used for "Assigned Owner", which the forms send as a name.
    """
    try:
        condition: ColumnElement[bool] = m.User.id == UUID(ref)
    except ValueError:
        condition = func.lower(m.User.name) == ref.strip().lower()
    candidates = (await db_session.execute(select(m.User).where(condition))).scalars().unique()
    for user in candidates:
        if user.is_active and user.can_access_business(business_id):
            return user
    raise ApplicationClientError(f"No active user named '{ref}' works in this business")


async def list_scoped[ModelT: Any](
    service: SQLAlchemyAsyncRepositoryService[ModelT],
    user: m.User,
    query: ListQuery,
    *,
    search: list[InstrumentedAttribute[Any]],
    status_enum: type[StrEnum] | None = None,
) -> tuple[list[ModelT], int]:
    """One page of a business-scoped table, newest first, with the table's search and filters."""
    model = service.repository.model_type
    filters: list[Any] = []
    if query.business:
        business = await resolve_business(service.repository.session, user, query.business)
        filters.append(model.business_id == business.id)
    elif (scope := business_filter(user, model.business_id)) is not None:
        filters.append(scope)
    if query.status and status_enum is not None:
        try:
            filters.append(model.status == status_enum(query.status))
        except ValueError:
            allowed = ", ".join(s.value for s in status_enum)
            raise ApplicationClientError(f"Unknown status '{query.status}'. Use one of: {allowed}") from None
    if query.search:
        escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(or_(*(column.ilike(f"%{escaped}%", escape="\\") for column in search)))
    items, total = await service.get_many_and_count(
        *filters, LimitOffset(limit=query.page_size, offset=query.offset), OrderBy("created_at", "desc")
    )
    return list(items), total


async def get_scoped[ModelT: Any](
    service: SQLAlchemyAsyncRepositoryService[ModelT], user: m.User, item_id: UUID
) -> ModelT:
    """Fetch a row by id. Rows in other businesses look missing rather than forbidden."""
    model = service.repository.model_type
    item = await service.get_one_or_none(model.id == item_id)
    if item is None or not user.can_access_business(item.business_id):
        raise NotFoundException(detail=f"{model.__name__} not found")
    return item
