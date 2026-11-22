from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.extensions.litestar.providers import create_service_provider

from app.db import models as m


class ContactService(service.SQLAlchemyAsyncRepositoryService[m.Contact]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Contact]):
        model_type = m.Contact

    repository_type = Repo


class UniversityService(service.SQLAlchemyAsyncRepositoryService[m.University]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.University]):
        model_type = m.University

    repository_type = Repo


class ConsultantService(service.SQLAlchemyAsyncRepositoryService[m.Consultant]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Consultant]):
        model_type = m.Consultant

    repository_type = Repo


class PipelineStageService(service.SQLAlchemyAsyncRepositoryService[m.PipelineStage]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.PipelineStage]):
        model_type = m.PipelineStage

    repository_type = Repo


class DealService(service.SQLAlchemyAsyncRepositoryService[m.Deal]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Deal]):
        model_type = m.Deal

    repository_type = Repo


class DealMessageService(service.SQLAlchemyAsyncRepositoryService[m.DealMessage]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.DealMessage]):
        model_type = m.DealMessage

    repository_type = Repo


class DealActivityService(service.SQLAlchemyAsyncRepositoryService[m.DealActivity]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.DealActivity]):
        model_type = m.DealActivity

    repository_type = Repo


provide_contact_service = create_service_provider(
    ContactService,
    error_messages={"integrity": "This contact is used by quotations, orders or invoices and can't be deleted."},
)
provide_university_service = create_service_provider(UniversityService)
provide_consultant_service = create_service_provider(ConsultantService)
provide_stage_service = create_service_provider(PipelineStageService)
provide_deal_service = create_service_provider(DealService)
provide_deal_message_service = create_service_provider(DealMessageService)
provide_deal_activity_service = create_service_provider(DealActivityService)
