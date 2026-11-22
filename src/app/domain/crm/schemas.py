"""Request and response bodies for CRM. Response field names match the frontend's types."""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

import msgspec

from app.db import models as m
from app.domain.accounts.schemas import UserSummary
from app.lib.schema import CamelizedBaseStruct

Name = Annotated[str, msgspec.Meta(min_length=1, max_length=200)]
Email = Annotated[str, msgspec.Meta(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)]
Phone = Annotated[str, msgspec.Meta(max_length=50)]
Country = Annotated[str, msgspec.Meta(max_length=100)]
Business = Annotated[str, msgspec.Meta(min_length=1, description="Business id, name or slug")]
Owner = Annotated[str, msgspec.Meta(min_length=1, description="User id or full name")]
Color = Annotated[str, msgspec.Meta(pattern=r"^#[0-9A-Fa-f]{6}$")]
Tag = Annotated[str, msgspec.Meta(min_length=1, max_length=50)]
Rating = Annotated[int, msgspec.Meta(ge=0, le=5)]
Amount = Annotated[float, msgspec.Meta(ge=0)]


# ---------- Contacts ----------
class Contact(CamelizedBaseStruct):
    id: UUID
    name: str
    company: str | None
    email: str | None
    phone: str | None
    business: str
    business_id: UUID
    owner: str | None
    owner_id: UUID | None
    follow_up_date: dt.date | None
    status: m.ContactStatus
    notes: str | None

    @classmethod
    def from_model(cls, c: m.Contact) -> Contact:
        return cls(
            id=c.id,
            name=c.name,
            company=c.company_name,
            email=c.email,
            phone=c.phone,
            business=c.business.name,
            business_id=c.business_id,
            owner=c.owner.name if c.owner else None,
            owner_id=c.owner_id,
            follow_up_date=c.follow_up_date,
            status=c.status,
            notes=c.notes,
        )


class ContactCreate(CamelizedBaseStruct):
    name: Name
    business: Business
    company: Name | None = None
    email: Email | None = None
    phone: Phone | None = None
    owner: Owner | None = None
    """Defaults to the signed-in user."""
    follow_up_date: dt.date | None = None
    status: m.ContactStatus = m.ContactStatus.LEAD
    notes: str | None = None


class ContactUpdate(CamelizedBaseStruct, omit_defaults=True):
    name: Name | msgspec.UnsetType = msgspec.UNSET
    business: Business | msgspec.UnsetType = msgspec.UNSET
    company: Name | None | msgspec.UnsetType = msgspec.UNSET
    email: Email | None | msgspec.UnsetType = msgspec.UNSET
    phone: Phone | None | msgspec.UnsetType = msgspec.UNSET
    owner: Owner | None | msgspec.UnsetType = msgspec.UNSET
    follow_up_date: dt.date | None | msgspec.UnsetType = msgspec.UNSET
    status: m.ContactStatus | msgspec.UnsetType = msgspec.UNSET
    notes: str | None | msgspec.UnsetType = msgspec.UNSET


# ---------- Universities ----------
class University(CamelizedBaseStruct):
    id: UUID
    name: str
    country: str | None
    email: str | None
    phone: str | None
    website: str | None
    business: str
    business_id: UUID
    status: m.RecordStatus

    @classmethod
    def from_model(cls, u: m.University) -> University:
        return cls(
            id=u.id,
            name=u.name,
            country=u.country,
            email=u.email,
            phone=u.phone,
            website=u.website,
            business=u.business.name,
            business_id=u.business_id,
            status=u.status,
        )


class UniversityCreate(CamelizedBaseStruct):
    name: Name
    business: Business
    country: Country | None = None
    email: Email | None = None
    phone: Phone | None = None
    website: Annotated[str, msgspec.Meta(max_length=300)] | None = None
    status: m.RecordStatus = m.RecordStatus.ACTIVE


class UniversityUpdate(CamelizedBaseStruct, omit_defaults=True):
    name: Name | msgspec.UnsetType = msgspec.UNSET
    business: Business | msgspec.UnsetType = msgspec.UNSET
    country: Country | None | msgspec.UnsetType = msgspec.UNSET
    email: Email | None | msgspec.UnsetType = msgspec.UNSET
    phone: Phone | None | msgspec.UnsetType = msgspec.UNSET
    website: Annotated[str, msgspec.Meta(max_length=300)] | None | msgspec.UnsetType = msgspec.UNSET
    status: m.RecordStatus | msgspec.UnsetType = msgspec.UNSET


# ---------- Consultants ----------
class Consultant(CamelizedBaseStruct):
    id: UUID
    name: str
    company: str | None
    country: str | None
    email: str | None
    phone: str | None
    business: str
    business_id: UUID
    status: m.RecordStatus

    @classmethod
    def from_model(cls, c: m.Consultant) -> Consultant:
        return cls(
            id=c.id,
            name=c.name,
            company=c.company_name,
            country=c.country,
            email=c.email,
            phone=c.phone,
            business=c.business.name,
            business_id=c.business_id,
            status=c.status,
        )


class ConsultantCreate(CamelizedBaseStruct):
    name: Name
    business: Business
    company: Name | None = None
    country: Country | None = None
    email: Email | None = None
    phone: Phone | None = None
    status: m.RecordStatus = m.RecordStatus.ACTIVE


class ConsultantUpdate(CamelizedBaseStruct, omit_defaults=True):
    name: Name | msgspec.UnsetType = msgspec.UNSET
    business: Business | msgspec.UnsetType = msgspec.UNSET
    company: Name | None | msgspec.UnsetType = msgspec.UNSET
    country: Country | None | msgspec.UnsetType = msgspec.UNSET
    email: Email | None | msgspec.UnsetType = msgspec.UNSET
    phone: Phone | None | msgspec.UnsetType = msgspec.UNSET
    status: m.RecordStatus | msgspec.UnsetType = msgspec.UNSET


# ---------- Pipeline ----------
class Deal(CamelizedBaseStruct):
    id: UUID
    stage_id: UUID
    contact_id: UUID | None
    name: str
    company: str | None
    amount: float | None
    tags: list[str]
    rating: int
    date: dt.date | None
    scheduled: bool
    position: int
    owner: UserSummary | None

    @classmethod
    def from_model(cls, d: m.Deal) -> Deal:
        return cls(
            id=d.id,
            stage_id=d.stage_id,
            contact_id=d.contact_id,
            name=d.name,
            company=d.contact.company_name if d.contact else None,
            amount=float(d.amount) if d.amount is not None else None,
            tags=list(d.tags or []),
            rating=d.rating,
            date=d.expected_date,
            scheduled=d.scheduled,
            position=d.position,
            owner=UserSummary.from_user(d.owner) if d.owner else None,
        )


class PipelineStage(CamelizedBaseStruct):
    id: UUID
    name: str
    color: str
    position: int
    progress: float
    """Share of the business's deals that sit in this stage, 0 to 1."""
    total: float
    """Sum of the stage's deal amounts."""
    deals: list[Deal]


class StageCreate(CamelizedBaseStruct):
    name: Annotated[str, msgspec.Meta(min_length=1, max_length=100)]
    business: Business
    color: Color | None = None


class StageUpdate(CamelizedBaseStruct, omit_defaults=True):
    name: Annotated[str, msgspec.Meta(min_length=1, max_length=100)] | msgspec.UnsetType = msgspec.UNSET
    color: Color | msgspec.UnsetType = msgspec.UNSET
    position: Annotated[int, msgspec.Meta(ge=0)] | msgspec.UnsetType = msgspec.UNSET


class Ref(CamelizedBaseStruct):
    """A picked record shown by name (consultant, university)."""

    id: UUID
    name: str


class DealDetail(Deal):
    """The "Edit Pipeline" dialog. Email and phone are the linked contact's."""

    business: str
    business_id: UUID
    stage_name: str
    email: str | None
    phone: str | None
    social_media_link: str | None
    consultant: Ref | None
    opened_at: dt.datetime
    universities: list[Ref]

    @classmethod
    def from_model(cls, d: m.Deal) -> DealDetail:  # type: ignore[override]
        base = Deal.from_model(d)
        return cls(
            **{f: getattr(base, f) for f in Deal.__struct_fields__},
            business=d.business.name,
            business_id=d.business_id,
            stage_name=d.stage.name,
            email=d.contact.email if d.contact else None,
            phone=d.contact.phone if d.contact else None,
            social_media_link=d.social_media_link,
            consultant=Ref(id=d.consultant.id, name=d.consultant.name) if d.consultant else None,
            opened_at=d.opened_at,
            universities=[Ref(id=u.id, name=u.name) for u in sorted(d.universities, key=lambda u: u.name)],
        )


Url = Annotated[str, msgspec.Meta(max_length=300)]


class DealCreate(CamelizedBaseStruct):
    """A card in a stage. Without `contactId`, a new Lead contact is created from name/company/email/phone."""

    name: Name
    contact_id: UUID | None = None
    company: Name | None = None
    email: Email | None = None
    phone: Phone | None = None
    amount: Amount | None = None
    tags: list[Tag] = msgspec.field(default_factory=list)
    rating: Rating = 0
    date: dt.date | None = None
    scheduled: bool = False
    owner: Owner | None = None
    """Defaults to the signed-in user."""
    social_media_link: Url | None = None
    consultant_id: UUID | None = None
    university_ids: list[UUID] = msgspec.field(default_factory=list)


class DealUpdate(CamelizedBaseStruct, omit_defaults=True):
    """Also used to move a card: send `stageId` and/or `position` (the index in the stage, without this deal)."""

    name: Name | msgspec.UnsetType = msgspec.UNSET
    stage_id: UUID | msgspec.UnsetType = msgspec.UNSET
    position: Annotated[int, msgspec.Meta(ge=0)] | msgspec.UnsetType = msgspec.UNSET
    amount: Amount | None | msgspec.UnsetType = msgspec.UNSET
    tags: list[Tag] | msgspec.UnsetType = msgspec.UNSET
    rating: Rating | msgspec.UnsetType = msgspec.UNSET
    date: dt.date | None | msgspec.UnsetType = msgspec.UNSET
    scheduled: bool | msgspec.UnsetType = msgspec.UNSET
    owner: Owner | None | msgspec.UnsetType = msgspec.UNSET
    contact: Name | msgspec.UnsetType = msgspec.UNSET
    """Renames the deal and its linked contact."""
    email: Email | None | msgspec.UnsetType = msgspec.UNSET
    phone: Phone | None | msgspec.UnsetType = msgspec.UNSET
    social_media_link: Url | None | msgspec.UnsetType = msgspec.UNSET
    consultant_id: UUID | None | msgspec.UnsetType = msgspec.UNSET
    opened_at: dt.datetime | msgspec.UnsetType = msgspec.UNSET
    university_ids: list[UUID] | msgspec.UnsetType = msgspec.UNSET


# ---------- Deal timeline ----------
class DealMessage(CamelizedBaseStruct):
    id: UUID
    kind: m.DealMessageKind
    author: UserSummary | None
    recipient: str | None
    subject: str | None
    body: str
    stage_name: str | None
    created_at: dt.datetime

    @classmethod
    def from_model(cls, msg: m.DealMessage) -> DealMessage:
        return cls(
            id=msg.id,
            kind=msg.kind,
            author=UserSummary.from_user(msg.author) if msg.author else None,
            recipient=msg.recipient,
            subject=msg.subject,
            body=msg.body,
            stage_name=msg.stage_name,
            created_at=msg.created_at,
        )


class DealMessageCreate(CamelizedBaseStruct):
    """ "Send Message" (kind=message, with To/Subject) or "Long Note" (kind=note)."""

    body: Annotated[str, msgspec.Meta(min_length=1, max_length=10000)]
    kind: m.DealMessageKind = m.DealMessageKind.MESSAGE
    to: Annotated[str, msgspec.Meta(max_length=254)] | None = None
    subject: Annotated[str, msgspec.Meta(max_length=200)] | None = None


class DealActivity(CamelizedBaseStruct):
    id: UUID
    kind: m.ActivityKind
    summary: str
    due_date: dt.date | None
    assigned_to: UserSummary | None
    done: bool
    created_at: dt.datetime

    @classmethod
    def from_model(cls, a: m.DealActivity) -> DealActivity:
        return cls(
            id=a.id,
            kind=a.kind,
            summary=a.summary,
            due_date=a.due_date,
            assigned_to=UserSummary.from_user(a.assigned_to) if a.assigned_to else None,
            done=a.done_at is not None,
            created_at=a.created_at,
        )


Summary = Annotated[str, msgspec.Meta(min_length=1, max_length=200)]


class DealActivityCreate(CamelizedBaseStruct):
    kind: m.ActivityKind = m.ActivityKind.TODO
    summary: Summary | None = None
    """Defaults to the activity type ("To Do", "Call"...)."""
    due_date: dt.date | None = None
    assigned_to: Owner | None = None
    """User id or full name. Defaults to the signed-in user."""


class DealActivityUpdate(CamelizedBaseStruct, omit_defaults=True):
    kind: m.ActivityKind | msgspec.UnsetType = msgspec.UNSET
    summary: Summary | msgspec.UnsetType = msgspec.UNSET
    due_date: dt.date | None | msgspec.UnsetType = msgspec.UNSET
    assigned_to: Owner | None | msgspec.UnsetType = msgspec.UNSET
    done: bool | msgspec.UnsetType = msgspec.UNSET
