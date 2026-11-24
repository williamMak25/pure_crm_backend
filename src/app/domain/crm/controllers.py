"""CRM: contacts, universities, consultants and the deal pipeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from datetime import date as dt_date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from advanced_alchemy.filters import OrderBy
from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import FromPath, FromQuery, JSONBody, QueryParameter
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import func, or_, select

from app.db import models as m
from app.domain.accounts.guards import requires_permission
from app.domain.accounts.schemas import UserSummary
from app.domain.crm.schemas import (
    LEAD_INPUT_STATUSES,
    Consultant,
    ConsultantCreate,
    ConsultantUpdate,
    Contact,
    ContactCreate,
    ContactUpdate,
    Deal,
    DealActivity,
    DealActivityCreate,
    DealActivityUpdate,
    DealCreate,
    DealDetail,
    DealMessage,
    DealMessageCreate,
    DealUpdate,
    Lead,
    LeadCreate,
    LeadUpdate,
    PipelineStage,
    StageCreate,
    StageUpdate,
    University,
    UniversityCreate,
    UniversityUpdate,
)
from app.domain.crm.services import (
    ConsultantService,
    ContactService,
    DealActivityService,
    DealMessageService,
    DealService,
    PipelineStageService,
    UniversityService,
    provide_consultant_service,
    provide_contact_service,
    provide_deal_activity_service,
    provide_deal_message_service,
    provide_deal_service,
    provide_stage_service,
    provide_university_service,
)
from app.domain.organization.scope import (
    ListQuery,
    company_members,
    get_scoped,
    list_scoped,
    provide_list_query,
    resolve_user,
)
from app.lib.exceptions import ApplicationClientError
from app.lib.schema import Paginated

can_read = requires_permission(m.AppModule.CRM, m.PermissionAction.READ)
can_create = requires_permission(m.AppModule.CRM, m.PermissionAction.CREATE)
can_update = requires_permission(m.AppModule.CRM, m.PermissionAction.UPDATE)
can_delete = requires_permission(m.AppModule.CRM, m.PermissionAction.DELETE)

STAGE_COLORS = ("#22C55E", "#F97316", "#D51F2E", "#3B82F6", "#8B5CF6", "#EAB308")
"""Colors given to new stages in turn: the four from the Figma pipeline, then two more."""

list_query_dependency = Provide(provide_list_query, sync_to_thread=False)


async def apply_changes(
    item: Any, changes: dict[str, Any], service: Any, renames: dict[str, str] | None = None
) -> None:
    """Copy a PATCH body onto a company row. `owner` arrives as a name and is resolved here."""
    session = service.repository.session
    if "owner" in changes:
        ref = changes.pop("owner")
        owner = await resolve_user(session, ref, item.business_id) if ref else None
        item.owner_id, item.owner = (owner.id if owner else None), owner
    for key, value in changes.items():
        setattr(item, (renames or {}).get(key, key), value)


def page_of[T](items: list[T], total: int, query: ListQuery) -> Paginated[T]:
    return Paginated(items=items, total=total, page=query.page, page_size=query.page_size)


class ContactController(Controller):
    path = "/crm/contacts"
    tags = ["CRM"]
    dependencies = {"contacts_service": Provide(provide_contact_service), "list_query": list_query_dependency}

    @get(operation_id="ListContacts", guards=[can_read])
    async def list_contacts(
        self,
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[Contact]:
        """Students (Contact List). Leads are under /crm/leads. Filter with `status` and `search`."""
        items, total = await list_scoped(
            contacts_service,
            company,
            list_query,
            search=[m.Contact.name, m.Contact.company_name, m.Contact.email],
            status_enum=m.ContactStatus,
            where=[m.Contact.kind == m.ContactKind.STUDENT],
        )
        return page_of([Contact.from_model(c) for c in items], total, list_query)

    @post(operation_id="CreateContact", guards=[can_create])
    async def create_contact(
        self,
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[ContactCreate],
    ) -> Contact:
        session = contacts_service.repository.session
        business = company
        owner = await resolve_user(session, data.owner, business.id) if data.owner else current_user
        contact = m.Contact(
            business_id=business.id,
            owner_id=owner.id,
            name=data.name,
            company_name=data.company,
            email=data.email,
            phone=data.phone,
            follow_up_date=data.follow_up_date,
            status=data.status,
            notes=data.notes,
        )
        contact.business, contact.owner = business, owner
        return Contact.from_model(await contacts_service.create(contact))

    @get("/{contact_id:uuid}", operation_id="GetContact", guards=[can_read])
    async def get_contact(
        self,
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        contact_id: FromPath[UUID],
    ) -> Contact:
        return Contact.from_model(
            await get_scoped(contacts_service, company, contact_id, m.Contact.kind == m.ContactKind.STUDENT)
        )

    @patch("/{contact_id:uuid}", operation_id="UpdateContact", guards=[can_update])
    async def update_contact(
        self,
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        contact_id: FromPath[UUID],
        data: JSONBody[ContactUpdate],
    ) -> Contact:
        contact = await get_scoped(contacts_service, company, contact_id, m.Contact.kind == m.ContactKind.STUDENT)
        await apply_changes(contact, data.to_dict(), contacts_service, {"company": "company_name"})
        return Contact.from_model(await contacts_service.update(contact))

    @delete("/{contact_id:uuid}", operation_id="DeleteContact", guards=[can_delete])
    async def delete_contact(
        self,
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        contact_id: FromPath[UUID],
    ) -> None:
        contact = await get_scoped(contacts_service, company, contact_id, m.Contact.kind == m.ContactKind.STUDENT)
        await contacts_service.delete(contact.id)


class LeadController(Controller):
    """The Leads tab. Setting a lead to "New" puts it on the pipeline's New stage ("In Pipeline")."""

    path = "/crm/leads"
    tags = ["CRM"]
    dependencies = {
        "contacts_service": Provide(provide_contact_service),
        "deals_service": Provide(provide_deal_service),
        "stages_service": Provide(provide_stage_service),
        "list_query": list_query_dependency,
    }

    @get(operation_id="ListLeads", guards=[can_read])
    async def list_leads(
        self,
        contacts_service: NamedDependency[ContactService],
        deals_service: NamedDependency[DealService],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[Lead]:
        """The company's leads. Filter with `status` (Open, Contacted, New, In Pipeline, Lost) and `search`."""
        items, total = await list_scoped(
            contacts_service,
            company,
            list_query,
            search=[m.Contact.name, m.Contact.company_name, m.Contact.email, m.Contact.phone],
            status_enum=m.LeadStatus,
            status_column=m.Contact.lead_status,
            where=[m.Contact.kind == m.ContactKind.LEAD],
        )
        deals = await _deals_by_contact(deals_service, [c.id for c in items])
        return page_of([Lead.from_model(c, deals.get(c.id)) for c in items], total, list_query)

    @post(operation_id="CreateLead", guards=[can_create])
    async def create_lead(
        self,
        contacts_service: NamedDependency[ContactService],
        deals_service: NamedDependency[DealService],
        stages_service: NamedDependency[PipelineStageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[LeadCreate],
    ) -> Lead:
        _check_lead_status(data.status)
        session = contacts_service.repository.session
        owner = await resolve_user(session, data.owner, company.id) if data.owner else current_user
        lead = m.Contact(
            business_id=company.id,
            owner_id=owner.id,
            kind=m.ContactKind.LEAD,
            lead_status=m.LeadStatus.OPEN if data.status == m.LeadStatus.NEW else data.status,
            name=data.name,
            company_name=data.company,
            email=data.email,
            phone=data.phone,
            follow_up_date=data.follow_up_date,
            notes=data.notes,
        )
        lead.business, lead.owner = company, owner
        lead = await contacts_service.create(lead)
        deal = None
        if data.status == m.LeadStatus.NEW:
            deal = await _send_to_pipeline(lead, company, current_user, deals_service, stages_service)
        return Lead.from_model(lead, deal)

    @get("/{lead_id:uuid}", operation_id="GetLead", guards=[can_read])
    async def get_lead(
        self,
        contacts_service: NamedDependency[ContactService],
        deals_service: NamedDependency[DealService],
        company: NamedDependency[m.Business],
        lead_id: FromPath[UUID],
    ) -> Lead:
        lead = await get_scoped(contacts_service, company, lead_id, m.Contact.kind == m.ContactKind.LEAD)
        return Lead.from_model(lead, (await _deals_by_contact(deals_service, [lead.id])).get(lead.id))

    @patch("/{lead_id:uuid}", operation_id="UpdateLead", guards=[can_update])
    async def update_lead(
        self,
        contacts_service: NamedDependency[ContactService],
        deals_service: NamedDependency[DealService],
        stages_service: NamedDependency[PipelineStageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        lead_id: FromPath[UUID],
        data: JSONBody[LeadUpdate],
    ) -> Lead:
        """Edit a lead. Changing the status to "New" moves it into the pipeline (once)."""
        lead = await get_scoped(contacts_service, company, lead_id, m.Contact.kind == m.ContactKind.LEAD)
        changes = data.to_dict()
        status = changes.pop("status", None)
        if status is not None:
            _check_lead_status(status)
        await apply_changes(lead, changes, contacts_service, {"company": "company_name"})
        deal = (await _deals_by_contact(deals_service, [lead.id])).get(lead.id)
        if status == m.LeadStatus.NEW:
            if deal is None:
                deal = await _send_to_pipeline(lead, company, current_user, deals_service, stages_service)
            lead.lead_status = m.LeadStatus.IN_PIPELINE
        elif status is not None:
            lead.lead_status = status
        lead = await contacts_service.update(lead)
        return Lead.from_model(lead, deal)

    @delete("/{lead_id:uuid}", operation_id="DeleteLead", guards=[can_delete])
    async def delete_lead(
        self,
        contacts_service: NamedDependency[ContactService],
        deals_service: NamedDependency[DealService],
        company: NamedDependency[m.Business],
        lead_id: FromPath[UUID],
    ) -> None:
        """Delete the lead and its pipeline card."""
        lead = await get_scoped(contacts_service, company, lead_id, m.Contact.kind == m.ContactKind.LEAD)
        for deal in await deals_service.get_many(m.Deal.contact_id == lead.id):
            await deals_service.delete(deal.id)
        await contacts_service.delete(lead.id)


class UniversityController(Controller):
    path = "/crm/universities"
    tags = ["CRM"]
    dependencies = {"universities_service": Provide(provide_university_service), "list_query": list_query_dependency}

    @get(operation_id="ListUniversities", guards=[can_read])
    async def list_universities(
        self,
        universities_service: NamedDependency[UniversityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[University]:
        items, total = await list_scoped(
            universities_service,
            company,
            list_query,
            search=[m.University.name, m.University.country, m.University.email],
            status_enum=m.RecordStatus,
        )
        return page_of([University.from_model(u) for u in items], total, list_query)

    @post(operation_id="CreateUniversity", guards=[can_create])
    async def create_university(
        self,
        universities_service: NamedDependency[UniversityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[UniversityCreate],
    ) -> University:
        business = company
        university = m.University(
            business_id=business.id,
            name=data.name,
            country=data.country,
            email=data.email,
            phone=data.phone,
            website=data.website,
            status=data.status,
        )
        university.business = business
        return University.from_model(await universities_service.create(university))

    @get("/{university_id:uuid}", operation_id="GetUniversity", guards=[can_read])
    async def get_university(
        self,
        universities_service: NamedDependency[UniversityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        university_id: FromPath[UUID],
    ) -> University:
        return University.from_model(await get_scoped(universities_service, company, university_id))

    @patch("/{university_id:uuid}", operation_id="UpdateUniversity", guards=[can_update])
    async def update_university(
        self,
        universities_service: NamedDependency[UniversityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        university_id: FromPath[UUID],
        data: JSONBody[UniversityUpdate],
    ) -> University:
        university = await get_scoped(universities_service, company, university_id)
        await apply_changes(university, data.to_dict(), universities_service)
        return University.from_model(await universities_service.update(university))

    @delete("/{university_id:uuid}", operation_id="DeleteUniversity", guards=[can_delete])
    async def delete_university(
        self,
        universities_service: NamedDependency[UniversityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        university_id: FromPath[UUID],
    ) -> None:
        university = await get_scoped(universities_service, company, university_id)
        await universities_service.delete(university.id)


class ConsultantController(Controller):
    path = "/crm/consultants"
    tags = ["CRM"]
    dependencies = {"consultants_service": Provide(provide_consultant_service), "list_query": list_query_dependency}

    @get(operation_id="ListConsultants", guards=[can_read])
    async def list_consultants(
        self,
        consultants_service: NamedDependency[ConsultantService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        list_query: NamedDependency[ListQuery],
    ) -> Paginated[Consultant]:
        items, total = await list_scoped(
            consultants_service,
            company,
            list_query,
            search=[m.Consultant.name, m.Consultant.company_name, m.Consultant.country, m.Consultant.email],
            status_enum=m.RecordStatus,
        )
        return page_of([Consultant.from_model(c) for c in items], total, list_query)

    @post(operation_id="CreateConsultant", guards=[can_create])
    async def create_consultant(
        self,
        consultants_service: NamedDependency[ConsultantService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[ConsultantCreate],
    ) -> Consultant:
        business = company
        consultant = m.Consultant(
            business_id=business.id,
            name=data.name,
            company_name=data.company,
            country=data.country,
            email=data.email,
            phone=data.phone,
            status=data.status,
        )
        consultant.business = business
        return Consultant.from_model(await consultants_service.create(consultant))

    @get("/{consultant_id:uuid}", operation_id="GetConsultant", guards=[can_read])
    async def get_consultant(
        self,
        consultants_service: NamedDependency[ConsultantService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        consultant_id: FromPath[UUID],
    ) -> Consultant:
        return Consultant.from_model(await get_scoped(consultants_service, company, consultant_id))

    @patch("/{consultant_id:uuid}", operation_id="UpdateConsultant", guards=[can_update])
    async def update_consultant(
        self,
        consultants_service: NamedDependency[ConsultantService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        consultant_id: FromPath[UUID],
        data: JSONBody[ConsultantUpdate],
    ) -> Consultant:
        consultant = await get_scoped(consultants_service, company, consultant_id)
        await apply_changes(consultant, data.to_dict(), consultants_service, {"company": "company_name"})
        return Consultant.from_model(await consultants_service.update(consultant))

    @delete("/{consultant_id:uuid}", operation_id="DeleteConsultant", guards=[can_delete])
    async def delete_consultant(
        self,
        consultants_service: NamedDependency[ConsultantService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        consultant_id: FromPath[UUID],
    ) -> None:
        consultant = await get_scoped(consultants_service, company, consultant_id)
        await consultants_service.delete(consultant.id)


class PipelineController(Controller):
    """The CRM kanban: stages (columns) and deals (cards), one board per business."""

    path = "/crm"
    tags = ["CRM"]
    dependencies = {
        "stages_service": Provide(provide_stage_service),
        "deals_service": Provide(provide_deal_service),
        "contacts_service": Provide(provide_contact_service),
        "messages_service": Provide(provide_deal_message_service),
        "activities_service": Provide(provide_deal_activity_service),
    }

    @get("/people", operation_id="ListCrmPeople", guards=[can_read])
    async def list_people(
        self,
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
    ) -> list[UserSummary]:
        """Active members of the company: the Saleperson / Assigned to pickers."""
        members = await company_members(deals_service.repository.session, company.id)
        return [UserSummary.from_user(u, company.id) for u in members]

    @get("/pipeline", operation_id="GetPipeline", guards=[can_read])
    async def get_pipeline(
        self,
        stages_service: NamedDependency[PipelineStageService],
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
    ) -> list[PipelineStage]:
        """Every stage of the company's pipeline, in order, with its deals."""
        found = company
        order = (OrderBy("position", "asc"), OrderBy("created_at", "asc"))
        stages = await stages_service.get_many(m.PipelineStage.business_id == found.id, *order)
        deals = await deals_service.get_many(m.Deal.business_id == found.id, *order)

        by_stage: dict[UUID, list[m.Deal]] = defaultdict(list)
        for deal in deals:
            by_stage[deal.stage_id].append(deal)
        return [
            PipelineStage(
                id=stage.id,
                name=stage.name,
                color=stage.color,
                position=stage.position,
                progress=len(by_stage[stage.id]) / len(deals) if deals else 0,
                total=float(sum((d.amount or Decimal(0) for d in by_stage[stage.id]), Decimal(0))),
                deals=[Deal.from_model(d) for d in by_stage[stage.id]],
            )
            for stage in stages
        ]

    @post("/pipeline", operation_id="CreatePipelineStage", guards=[can_create])
    async def create_stage(
        self,
        stages_service: NamedDependency[PipelineStageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        data: JSONBody[StageCreate],
    ) -> PipelineStage:
        business = company
        count = await stages_service.count(m.PipelineStage.business_id == business.id)
        stage = await stages_service.create(
            m.PipelineStage(
                business_id=business.id,
                name=data.name,
                color=data.color or STAGE_COLORS[count % len(STAGE_COLORS)],
                position=count,
            )
        )
        return PipelineStage(
            id=stage.id, name=stage.name, color=stage.color, position=stage.position, progress=0, total=0, deals=[]
        )

    @patch("/pipeline/{stage_id:uuid}", operation_id="UpdatePipelineStage", guards=[can_update])
    async def update_stage(
        self,
        stages_service: NamedDependency[PipelineStageService],
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        stage_id: FromPath[UUID],
        data: JSONBody[StageUpdate],
    ) -> PipelineStage:
        stage = await get_scoped(stages_service, company, stage_id)
        for key, value in data.to_dict().items():
            setattr(stage, key, value)
        stage = await stages_service.update(stage)
        deals = await deals_service.get_many(m.Deal.stage_id == stage.id, OrderBy("position", "asc"))
        all_deals = await deals_service.count(m.Deal.business_id == stage.business_id)
        return PipelineStage(
            id=stage.id,
            name=stage.name,
            color=stage.color,
            position=stage.position,
            progress=len(deals) / all_deals if all_deals else 0,
            total=float(sum((d.amount or Decimal(0) for d in deals), Decimal(0))),
            deals=[Deal.from_model(d) for d in deals],
        )

    @delete("/pipeline/{stage_id:uuid}", operation_id="DeletePipelineStage", guards=[can_delete])
    async def delete_stage(
        self,
        stages_service: NamedDependency[PipelineStageService],
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        stage_id: FromPath[UUID],
    ) -> None:
        stage = await get_scoped(stages_service, company, stage_id)
        if deals := await deals_service.count(m.Deal.stage_id == stage.id):
            raise ClientException(
                detail=f"Move or delete the {deals} deal(s) in {stage.name} first", status_code=HTTP_409_CONFLICT
            )
        await stages_service.delete(stage.id)

    @post("/pipeline/{stage_id:uuid}/deals", operation_id="CreateDeal", guards=[can_create])
    async def create_deal(
        self,
        stages_service: NamedDependency[PipelineStageService],
        deals_service: NamedDependency[DealService],
        contacts_service: NamedDependency[ContactService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        stage_id: FromPath[UUID],
        data: JSONBody[DealCreate],
    ) -> Deal:
        """Add a card to a stage, linked to an existing contact or to a new Lead."""
        stage = await get_scoped(stages_service, company, stage_id)
        session = deals_service.repository.session
        owner = await resolve_user(session, data.owner, stage.business_id) if data.owner else current_user

        if data.contact_id:
            contact = await get_scoped(contacts_service, company, data.contact_id)
            if contact.kind == m.ContactKind.LEAD:
                contact.lead_status = m.LeadStatus.IN_PIPELINE
            if contact.business_id != stage.business_id:
                raise ApplicationClientError("The contact belongs to a different business than the pipeline")
        else:
            contact = m.Contact(
                business_id=stage.business_id,
                owner_id=owner.id,
                name=data.name,
                company_name=data.company,
                email=data.email,
                phone=data.phone,
                kind=m.ContactKind.LEAD,
                lead_status=m.LeadStatus.IN_PIPELINE,
            )
            contact.business, contact.owner = stage.business, owner
            contact = await contacts_service.create(contact)

        deal = m.Deal(
            business_id=stage.business_id,
            stage_id=stage.id,
            contact_id=contact.id,
            owner_id=owner.id,
            name=data.name,
            amount=Decimal(str(data.amount)) if data.amount is not None else None,
            tags=data.tags,
            rating=data.rating,
            expected_date=data.date,
            scheduled=data.scheduled,
            position=await _next_position(deals_service, stage.id),
            social_media_link=data.social_media_link,
        )
        deal.business, deal.contact, deal.owner, deal.stage = stage.business, contact, owner, stage
        deal.consultant = await _consultant(session, data.consultant_id, stage.business_id)
        deal.consultant_id = deal.consultant.id if deal.consultant else None
        deal.university = await _university(session, data.university_id, stage.business_id)
        deal.university_id = deal.university.id if deal.university else None
        return Deal.from_model(await deals_service.create(deal))

    @get("/deals/{deal_id:uuid}", operation_id="GetDeal", guards=[can_read])
    async def get_deal(
        self,
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
    ) -> DealDetail:
        """Everything the "Edit Pipeline" dialog shows on its left side."""
        return DealDetail.from_model(await get_scoped(deals_service, company, deal_id))

    @patch("/deals/{deal_id:uuid}", operation_id="UpdateDeal", guards=[can_update])
    async def update_deal(
        self,
        stages_service: NamedDependency[PipelineStageService],
        deals_service: NamedDependency[DealService],
        contacts_service: NamedDependency[ContactService],
        messages_service: NamedDependency[DealMessageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
        data: JSONBody[DealUpdate],
    ) -> DealDetail:
        """Edit a card from the "Edit Pipeline" dialog, or move it with `stageId` / `position`."""
        deal = await get_scoped(deals_service, company, deal_id)
        session = deals_service.repository.session
        changes = data.to_dict()

        if "stage_id" in changes and changes["stage_id"] != deal.stage_id:
            target = await get_scoped(stages_service, company, changes["stage_id"])
            if target.business_id != deal.business_id:
                raise ApplicationClientError("A deal can only move to a stage in the same business")
            changes.setdefault("position", await _next_position(deals_service, target.id))
            # Log the move on the timeline, like the "› Consultation (Stage)" notes in the design.
            await messages_service.create(
                m.DealMessage(
                    deal_id=deal.id,
                    author_id=current_user.id,
                    kind=m.DealMessageKind.NOTE,
                    body=f"Stage changed from {deal.stage.name} to {target.name}",
                    stage_name=target.name,
                )
            )
            deal.stage = target
        if "amount" in changes and changes["amount"] is not None:
            changes["amount"] = Decimal(str(changes["amount"]))
        if "position" in changes:
            # Drag and drop: renumber the target stage with the deal at the requested index.
            target_stage = changes.get("stage_id", deal.stage_id)
            siblings = list(
                await deals_service.get_many(
                    m.Deal.stage_id == target_stage,
                    m.Deal.id != deal.id,
                    OrderBy("position", "asc"),
                    OrderBy("created_at", "asc"),
                )
            )
            siblings.insert(min(changes.pop("position"), len(siblings)), deal)
            for index, sibling in enumerate(siblings):
                sibling.position = index

        # Contact name, email and phone live on the linked contact.
        contact_fields = {k: changes.pop(k) for k in ("contact", "email", "phone") if k in changes}
        if contact_fields:
            if deal.contact is None:
                deal.contact = await contacts_service.create(
                    m.Contact(business_id=deal.business_id, owner_id=deal.owner_id, name=deal.name)
                )
                deal.contact_id = deal.contact.id
            if "contact" in contact_fields:
                deal.name = deal.contact.name = contact_fields["contact"]
            if "email" in contact_fields:
                deal.contact.email = contact_fields["email"]
            if "phone" in contact_fields:
                deal.contact.phone = contact_fields["phone"]
        if "consultant_id" in changes:
            deal.consultant = await _consultant(session, changes.pop("consultant_id"), deal.business_id)
            deal.consultant_id = deal.consultant.id if deal.consultant else None
        if "university_id" in changes:
            deal.university = await _university(session, changes.pop("university_id"), deal.business_id)
            deal.university_id = deal.university.id if deal.university else None

        await apply_changes(deal, changes, deals_service, {"date": "expected_date"})
        return DealDetail.from_model(await deals_service.update(deal))

    @get("/deals/{deal_id:uuid}/messages", operation_id="ListDealMessages", guards=[can_read])
    async def list_messages(
        self,
        deals_service: NamedDependency[DealService],
        messages_service: NamedDependency[DealMessageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
        kind: FromQuery[m.DealMessageKind | None] = None,
        search: Annotated[str | None, QueryParameter(max_length=100)] = None,
    ) -> list[DealMessage]:
        """The deal's timeline, newest first. `kind=message` for Send Message, `kind=note` for Long Note."""
        deal = await get_scoped(deals_service, company, deal_id)
        filters: list[Any] = [m.DealMessage.deal_id == deal.id]
        if kind:
            filters.append(m.DealMessage.kind == kind)
        if search and search.strip():
            like = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            filters.append(
                or_(m.DealMessage.body.ilike(like, escape="\\"), m.DealMessage.subject.ilike(like, escape="\\"))
            )
        messages = await messages_service.get_many(*filters, OrderBy("created_at", "desc"))
        return [DealMessage.from_model(msg) for msg in messages]

    @post("/deals/{deal_id:uuid}/messages", operation_id="CreateDealMessage", guards=[can_create])
    async def create_message(
        self,
        deals_service: NamedDependency[DealService],
        messages_service: NamedDependency[DealMessageService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
        data: JSONBody[DealMessageCreate],
    ) -> DealMessage:
        """Log a message to the contact or an internal note. Messages are recorded, not emailed."""
        deal = await get_scoped(deals_service, company, deal_id)
        is_message = data.kind == m.DealMessageKind.MESSAGE
        message = m.DealMessage(
            deal_id=deal.id,
            author_id=current_user.id,
            kind=data.kind,
            recipient=(data.to or (deal.contact.email if deal.contact else None)) if is_message else None,
            subject=data.subject,
            body=data.body,
            stage_name=deal.stage.name,
        )
        message.author = current_user
        return DealMessage.from_model(await messages_service.create(message))

    @get("/deals/{deal_id:uuid}/activities", operation_id="ListDealActivities", guards=[can_read])
    async def list_activities(
        self,
        deals_service: NamedDependency[DealService],
        activities_service: NamedDependency[DealActivityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
    ) -> list[DealActivity]:
        """Open activities first (by due date), then done ones."""
        deal = await get_scoped(deals_service, company, deal_id)
        activities = await activities_service.get_many(m.DealActivity.deal_id == deal.id)
        ordered = sorted(activities, key=lambda a: (a.done_at is not None, a.due_date or dt_date.max, a.created_at))
        return [DealActivity.from_model(a) for a in ordered]

    @post("/deals/{deal_id:uuid}/activities", operation_id="CreateDealActivity", guards=[can_create])
    async def create_activity(
        self,
        deals_service: NamedDependency[DealService],
        activities_service: NamedDependency[DealActivityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
        data: JSONBody[DealActivityCreate],
    ) -> DealActivity:
        deal = await get_scoped(deals_service, company, deal_id)
        session = deals_service.repository.session
        assignee = await resolve_user(session, data.assigned_to, deal.business_id) if data.assigned_to else current_user
        activity = m.DealActivity(
            deal_id=deal.id,
            kind=data.kind,
            summary=data.summary or data.kind.value,
            due_date=data.due_date,
            assigned_to_id=assignee.id,
            created_by_id=current_user.id,
        )
        activity.assigned_to = assignee
        return DealActivity.from_model(await activities_service.create(activity))

    @patch("/deal-activities/{activity_id:uuid}", operation_id="UpdateDealActivity", guards=[can_update])
    async def update_activity(
        self,
        deals_service: NamedDependency[DealService],
        activities_service: NamedDependency[DealActivityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        activity_id: FromPath[UUID],
        data: JSONBody[DealActivityUpdate],
    ) -> DealActivity:
        """Edit an activity or mark it done with `{"done": true}`."""
        activity, deal = await _scoped_activity(activities_service, deals_service, company, activity_id)
        changes = data.to_dict()
        if "done" in changes:
            activity.done_at = datetime.now(UTC) if changes.pop("done") else None
        if "assigned_to" in changes:
            ref = changes.pop("assigned_to")
            assignee = await resolve_user(deals_service.repository.session, ref, deal.business_id) if ref else None
            activity.assigned_to, activity.assigned_to_id = assignee, assignee.id if assignee else None
        for key, value in changes.items():
            setattr(activity, key, value)
        return DealActivity.from_model(await activities_service.update(activity))

    @delete("/deal-activities/{activity_id:uuid}", operation_id="DeleteDealActivity", guards=[can_update])
    async def delete_activity(
        self,
        deals_service: NamedDependency[DealService],
        activities_service: NamedDependency[DealActivityService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        activity_id: FromPath[UUID],
    ) -> None:
        activity, _ = await _scoped_activity(activities_service, deals_service, company, activity_id)
        await activities_service.delete(activity.id)

    @delete("/deals/{deal_id:uuid}", operation_id="DeleteDeal", guards=[can_delete])
    async def delete_deal(
        self,
        deals_service: NamedDependency[DealService],
        current_user: NamedDependency[m.User],
        company: NamedDependency[m.Business],
        deal_id: FromPath[UUID],
    ) -> None:
        """Remove the card. Its lead stays in Leads and goes back to "Open" if it has no other card."""
        deal = await get_scoped(deals_service, company, deal_id)
        lead = deal.contact if deal.contact and deal.contact.kind == m.ContactKind.LEAD else None
        await deals_service.delete(deal.id)
        if lead is not None and not await deals_service.count(m.Deal.contact_id == lead.id):
            lead.lead_status = m.LeadStatus.OPEN
            await deals_service.repository.session.flush()


async def _next_position(deals_service: DealService, stage_id: UUID) -> int:
    statement = select(func.coalesce(func.max(m.Deal.position) + 1, 0)).where(m.Deal.stage_id == stage_id)
    return (await deals_service.repository.session.execute(statement)).scalar_one()


async def _consultant(session: Any, consultant_id: UUID | None, business_id: UUID) -> m.Consultant | None:
    if consultant_id is None:
        return None
    consultant = await session.get(m.Consultant, consultant_id)
    if consultant is None or consultant.business_id != business_id:
        raise ApplicationClientError("Pick a consultant from the same business as the deal")
    return consultant


async def _university(session: Any, university_id: UUID | None, business_id: UUID) -> m.University | None:
    """The one university picked for a lead; it must belong to the deal's company."""
    if university_id is None:
        return None
    university = await session.get(m.University, university_id)
    if university is None or university.business_id != business_id:
        raise ApplicationClientError("Pick a university from this company")
    return university


async def _scoped_activity(
    activities_service: DealActivityService, deals_service: DealService, company: m.Business, activity_id: UUID
) -> tuple[m.DealActivity, m.Deal]:
    activity = await activities_service.get_one_or_none(m.DealActivity.id == activity_id)
    if activity is None:
        raise NotFoundException(detail="Activity not found")
    deal = await get_scoped(deals_service, company, activity.deal_id)
    return activity, deal


def _check_lead_status(status: m.LeadStatus) -> None:
    if status not in LEAD_INPUT_STATUSES:
        raise ApplicationClientError('Pick Open, Contacted, New or Lost. "In Pipeline" is set when the lead moves.')


async def _deals_by_contact(deals_service: DealService, contact_ids: list[UUID]) -> dict[UUID, m.Deal]:
    """The (oldest) pipeline card of each contact."""
    if not contact_ids:
        return {}
    deals = await deals_service.get_many(m.Deal.contact_id.in_(contact_ids), OrderBy("created_at", "asc"))
    found: dict[UUID, m.Deal] = {}
    for deal in deals:
        found.setdefault(deal.contact_id, deal)  # type: ignore[arg-type]
    return found


async def _send_to_pipeline(
    lead: m.Contact,
    company: m.Business,
    user: m.User,
    deals_service: DealService,
    stages_service: PipelineStageService,
) -> m.Deal:
    """Put the lead on the pipeline's "New" stage (or the first stage) and mark it "In Pipeline"."""
    stages = await stages_service.get_many(
        m.PipelineStage.business_id == company.id, OrderBy("position", "asc"), OrderBy("created_at", "asc")
    )
    if not stages:
        raise ApplicationClientError("This company's pipeline has no stages yet. Add one on the Pipeline tab first.")
    stage = next((st for st in stages if st.name.strip().lower() == "new"), stages[0])
    deal = m.Deal(
        business_id=company.id,
        stage_id=stage.id,
        contact_id=lead.id,
        owner_id=lead.owner_id or user.id,
        name=lead.name,
        tags=[],
        expected_date=lead.follow_up_date,
        position=await _next_position(deals_service, stage.id),
    )
    deal.business, deal.stage, deal.contact, deal.owner = company, stage, lead, lead.owner or user
    deal = await deals_service.create(deal)
    session = deals_service.repository.session
    session.add(
        m.DealMessage(
            deal_id=deal.id,
            author_id=user.id,
            kind=m.DealMessageKind.NOTE,
            body="Moved here from Leads",
            stage_name=stage.name,
        )
    )
    lead.lead_status = m.LeadStatus.IN_PIPELINE
    await session.flush()
    return deal
