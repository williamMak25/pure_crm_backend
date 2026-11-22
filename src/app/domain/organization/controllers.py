from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.extensions.litestar.providers import create_service_provider
from litestar import Controller, Request, get
from litestar.di import NamedDependency, Provide
from litestar.security.jwt import Token

from app.db import models as m
from app.lib.schema import CamelizedBaseStruct


class BusinessService(service.SQLAlchemyAsyncRepositoryService[m.Business]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Business]):
        model_type = m.Business

    repository_type = Repo


provide_business_service = create_service_provider(BusinessService)


class Business(CamelizedBaseStruct):
    """The frontend's `Business` type."""

    id: UUID
    name: str


class BusinessController(Controller):
    path = "/businesses"
    tags = ["Organization"]
    dependencies = {"business_service": Provide(provide_business_service)}

    @get(operation_id="ListBusinesses")
    async def list_businesses(
        self, request: Request[m.User, Token, Any], business_service: NamedDependency[BusinessService]
    ) -> list[Business]:
        """Business units the signed-in user can switch to. Administrators see all of them."""
        user = request.user
        businesses = await business_service.get_many() if user.is_superuser else user.businesses
        return [Business(id=b.id, name=b.name) for b in sorted(businesses, key=lambda b: b.name)]
