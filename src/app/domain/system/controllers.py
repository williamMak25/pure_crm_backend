from __future__ import annotations

from litestar import Controller, MediaType, Response, get
from litestar.di import NamedDependency
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class SystemController(Controller):
    tags = ["System"]

    @get("/health", operation_id="Health", media_type=MediaType.JSON, exclude_from_auth=True, security=[])
    async def health(self, db_session: NamedDependency[AsyncSession]) -> Response[dict[str, str]]:
        """Liveness and database check, used by the Docker healthcheck."""
        try:
            await db_session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            return Response({"status": "degraded", "database": "offline"}, status_code=503)
        return Response({"status": "ok", "database": "online"})
