"""Company scoping and list parameters shared by every module.

Each entry in the navbar switcher is a separate company (a `business` row). The frontend sends the
selected one in the `X-Company` header; every list, create and lookup is limited to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, PermissionDeniedException
from litestar.params import FromQuery, QueryParameter
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.lib.exceptions import ApplicationClientError

if TYPE_CHECKING:
    from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
    from litestar import Request
    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import InstrumentedAttribute

COMPANY_HEADER = "x-company"
"""Company id, name or slug chosen in the navbar switcher."""


@dataclass
class ListQuery:
    """`ListParams` sent by the frontend's tables."""

    page: int
    page_size: int
    search: str | None
    status: str | None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def provide_list_query(
    page: Annotated[int, QueryParameter(ge=1)] = 1,
    page_size: Annotated[int, QueryParameter(name="pageSize", ge=1, le=100)] = 10,
    search: Annotated[str | None, QueryParameter(max_length=100)] = None,
    status: FromQuery[str | None] = None,
) -> ListQuery:
    return ListQuery(page=page, page_size=page_size, search=(search or "").strip() or None, status=status or None)


def _matches(business: m.Business, ref: str) -> bool:
    ref = ref.strip().lower()
    return ref in {str(business.id), business.name.lower(), business.slug}


def member_company(user: m.User, ref: str | None) -> m.Business | None:
    """The user's company named by `ref`, or their default / first company when `ref` is empty."""
    if ref:
        return next((b for b in user.businesses if _matches(b, ref)), None)
    default = next((b for b in user.businesses if b.id == user.default_business_id), None)
    return default or (user.businesses[0] if user.businesses else None)


async def find_company(db_session: AsyncSession, user: m.User, ref: str | None) -> m.Business:
    """Resolve the selected company and check the user belongs to it (super admins reach every company)."""
    company = member_company(user, ref)
    if company is not None:
        return company
    if user.is_superuser:
        statement = select(m.Business).order_by(m.Business.name).limit(1)
        if ref:
            try:
                condition: ColumnElement[bool] = m.Business.id == UUID(ref)
            except ValueError:
                condition = or_(
                    func.lower(m.Business.name) == ref.strip().lower(), m.Business.slug == ref.strip().lower()
                )
            statement = select(m.Business).where(condition)
        if (found := (await db_session.execute(statement)).scalar_one_or_none()) is not None:
            return found
    if ref:
        raise PermissionDeniedException(detail=f"You are not a member of '{ref}'")
    raise PermissionDeniedException(detail="You are not a member of any company yet. Ask an administrator to add you.")


async def provide_company(request: Request[m.User, Any, Any], db_session: NamedDependency[AsyncSession]) -> m.Business:
    """The company of this request (`company` dependency)."""
    return await find_company(db_session, request.user, request.headers.get(COMPANY_HEADER))


async def resolve_user(db_session: AsyncSession, ref: str, business_id: UUID) -> m.User:
    """Find an active member of the company by id or name (case-insensitive).

    Used for "Assigned Owner", which the forms send as a name.
    """
    try:
        condition: ColumnElement[bool] = m.User.id == UUID(ref)
    except ValueError:
        condition = func.lower(m.User.name) == ref.strip().lower()
    candidates = (await db_session.execute(select(m.User).where(condition))).scalars().unique()
    for user in candidates:
        if user.is_active and (user.is_superuser or user.membership(business_id)):
            return user
    raise ApplicationClientError(f"No active member named '{ref}' in this company")


async def company_members(db_session: AsyncSession, business_id: UUID) -> list[m.User]:
    """Active members of a company, by name."""
    statement = (
        select(m.User)
        .join(m.Membership, m.Membership.user_id == m.User.id)
        .where(m.Membership.business_id == business_id, m.User.status == m.RecordStatus.ACTIVE)
        .order_by(m.User.name)
    )
    return list((await db_session.execute(statement)).scalars().unique())


async def list_scoped[ModelT: Any](
    service: SQLAlchemyAsyncRepositoryService[ModelT],
    company: m.Business,
    query: ListQuery,
    *,
    search: list[InstrumentedAttribute[Any]],
    status_enum: type[StrEnum] | None = None,
    status_column: InstrumentedAttribute[Any] | None = None,
    where: list[Any] | None = None,
) -> tuple[list[ModelT], int]:
    """One page of the company's rows, newest first, with the table's search and filters.

    `where` adds fixed conditions (e.g. only leads); `status_column` defaults to the model's `status`.
    """
    model = service.repository.model_type
    filters: list[Any] = [model.business_id == company.id, *(where or [])]
    if query.status and status_enum is not None:
        try:
            filters.append((status_column if status_column is not None else model.status) == status_enum(query.status))
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
    service: SQLAlchemyAsyncRepositoryService[ModelT], company: m.Business, item_id: UUID, *where: Any
) -> ModelT:
    """Fetch a row by id. Rows of other companies (or not matching `where`) look missing rather than forbidden."""
    model = service.repository.model_type
    item = await service.get_one_or_none(model.id == item_id, *where)
    if item is None or item.business_id != company.id:
        raise NotFoundException(detail=f"{model.__name__} not found")
    return item
