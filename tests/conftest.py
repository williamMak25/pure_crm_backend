"""Tests run against a separate `<db>_test` database in the same Postgres container.

Start it first: `docker compose up -d db`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import asyncpg
import pytest
from sqlalchemy.engine import make_url

_dev_url = make_url(os.environ.get("DATABASE_URL", "postgresql+asyncpg://pure:pure@localhost:5434/pure_erp"))
TEST_DB = f"{_dev_url.database}_test"
os.environ["DATABASE_URL"] = _dev_url.set(database=TEST_DB).render_as_string(hide_password=False)
os.environ["DATABASE_POOL_DISABLED"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long"
os.environ["ALLOWED_CORS_ORIGINS"] = "http://localhost:5173"

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from litestar.testing import AsyncTestClient

ADMIN = ("admin@test.local", "Admin123!")
SALES = ("sales@test.local", "Sales123!")


async def _ensure_database() -> None:
    conn = await asyncpg.connect(
        user=_dev_url.username,
        password=_dev_url.password,
        host=_dev_url.host,
        port=_dev_url.port,
        database="postgres",
    )
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB):
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    from advanced_alchemy.base import orm_registry
    from sqlalchemy import text

    from app.cli.commands import _create_user, _seed
    from app.config import alchemy
    from app.db import models  # noqa: F401  (register every table)

    await _ensure_database()
    engine = alchemy.get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(orm_registry.metadata.create_all)
    async with alchemy.get_session() as session:
        await _seed(session, ADMIN[0], ADMIN[1], "Test Admin")
        await _create_user(session, SALES[0], "Test Sales", SALES[1], "Sales", ("pure-education",))
        await session.commit()
    yield
    await engine.dispose()


@pytest.fixture(scope="session")
def app() -> Litestar:
    from litestar import get

    from app.db import models as m
    from app.domain.accounts.guards import requires_permission
    from app.server.asgi import create_app

    @get("/api/_test/hr", guards=[requires_permission(m.AppModule.HR, m.PermissionAction.READ)], sync_to_thread=False)
    def hr_only() -> dict[str, str]:
        return {"ok": "hr"}

    application = create_app()
    application.register(hr_only)
    return application


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    from litestar.testing import AsyncTestClient

    async with AsyncTestClient(app=app) as test_client:
        yield test_client
