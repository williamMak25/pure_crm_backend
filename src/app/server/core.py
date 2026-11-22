"""Application core plugin: routes, auth, CORS, database and error handling."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
from litestar import Router
from litestar.di import Provide
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.plugins import CLIPluginProtocol, InitPluginProtocol

from app import config
from app.__metadata__ import __version__
from app.db import models as m
from app.domain.accounts.controllers import AuthController, MeController
from app.domain.accounts.guards import auth, provide_user
from app.domain.crm.controllers import (
    ConsultantController,
    ContactController,
    PipelineController,
    UniversityController,
)
from app.domain.organization.controllers import BusinessController
from app.domain.projects.controllers import ProjectController
from app.domain.system.controllers import SystemController
from app.lib.exceptions import exception_handlers
from app.lib.settings import AppSettings, get_settings, provide_app_settings

if TYPE_CHECKING:
    from click import Group
    from litestar.config.app import AppConfig


class ApplicationCore(InitPluginProtocol, CLIPluginProtocol):
    """Configures the Litestar app. Add each new domain controller to `api_router` below."""

    def on_cli_init(self, cli: Group) -> None:
        from app.cli.commands import seed_command, users_group

        cli.add_command(seed_command)
        cli.add_command(users_group)

    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        settings = get_settings()
        app_config.debug = settings.app.DEBUG
        app_config.openapi_config = OpenAPIConfig(
            title=settings.app.NAME,
            version=__version__,
            components=[auth.openapi_components],
            security=[auth.security_requirement],
            render_plugins=[ScalarRenderPlugin()],
        )
        app_config = auth.on_app_init(app_config)
        app_config.cors_config = config.cors
        app_config.plugins.append(SQLAlchemyPlugin(config=config.alchemy))

        api_router = Router(
            path=settings.app.API_PREFIX,
            route_handlers=[
                AuthController,
                MeController,
                BusinessController,
                ContactController,
                UniversityController,
                ConsultantController,
                PipelineController,
                ProjectController,
            ],
        )
        app_config.route_handlers.extend([SystemController, api_router])

        app_config.signature_namespace.update({"m": m, "UUID": UUID, "AppSettings": AppSettings})
        app_config.exception_handlers.update(exception_handlers)
        app_config.dependencies.update(
            {
                "current_user": Provide(provide_user, sync_to_thread=False),
                "settings": Provide(provide_app_settings, sync_to_thread=False),
            }
        )
        return app_config
