"""All configuration via environment.

Trimmed from the litestar-fullstack template: no Vite, SAQ, email or OAuth settings.
"""

from __future__ import annotations

import binascii
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from advanced_alchemy.extensions.litestar import AlembicAsyncConfig, AsyncSessionConfig, SQLAlchemyAsyncConfig
from dotenv import load_dotenv
from litestar.config.cors import CORSConfig
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.lib.env import get_env

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

BASE_DIR: Final[Path] = Path(__file__).parent.parent


@dataclass
class DatabaseSettings:
    URL: str = field(default_factory=get_env("DATABASE_URL", "postgresql+asyncpg://pure:pure@localhost:5434/pure_erp"))
    """SQLAlchemy Database URL."""
    ECHO: bool = field(default_factory=get_env("DATABASE_ECHO", False))
    """Enable SQLAlchemy engine logs."""
    POOL_DISABLED: bool = field(default_factory=get_env("DATABASE_POOL_DISABLED", False))
    """Disable connection pooling (useful for tests and one-shot CLI commands)."""
    POOL_SIZE: int = field(default_factory=get_env("DATABASE_POOL_SIZE", 5))
    """Pool size for SQLAlchemy connection pool."""
    POOL_MAX_OVERFLOW: int = field(default_factory=get_env("DATABASE_MAX_POOL_OVERFLOW", 10))
    """Max overflow for SQLAlchemy connection pool."""
    POOL_RECYCLE: int = field(default_factory=get_env("DATABASE_POOL_RECYCLE", 300))
    """Seconds before a pooled connection is recycled."""
    MIGRATION_CONFIG: str = field(
        default_factory=get_env("DATABASE_MIGRATION_CONFIG", f"{BASE_DIR}/db/migrations/alembic.ini")
    )
    """The path to the `alembic.ini` configuration file."""
    MIGRATION_PATH: str = field(default_factory=get_env("DATABASE_MIGRATION_PATH", f"{BASE_DIR}/db/migrations"))
    """The path to the `alembic` database migrations."""
    MIGRATION_DDL_VERSION_TABLE: str = field(
        default_factory=get_env("DATABASE_MIGRATION_DDL_VERSION_TABLE", "ddl_version")
    )
    """The name to use for the `alembic` versions table name."""
    _engine_instance: AsyncEngine | None = None

    def get_engine(self) -> AsyncEngine:
        if self._engine_instance is not None:
            return self._engine_instance
        url = self.URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        if self.POOL_DISABLED:
            self._engine_instance = create_async_engine(url, echo=self.ECHO, poolclass=NullPool)
        else:
            self._engine_instance = create_async_engine(
                url,
                echo=self.ECHO,
                pool_size=self.POOL_SIZE,
                max_overflow=self.POOL_MAX_OVERFLOW,
                pool_recycle=self.POOL_RECYCLE,
                pool_pre_ping=True,
                pool_use_lifo=True,
            )
        return self._engine_instance

    def get_config(self) -> SQLAlchemyAsyncConfig:
        return SQLAlchemyAsyncConfig(
            engine_instance=self.get_engine(),
            before_send_handler="autocommit",
            session_config=AsyncSessionConfig(expire_on_commit=False),
            alembic_config=AlembicAsyncConfig(
                version_table_name=self.MIGRATION_DDL_VERSION_TABLE,
                script_config=self.MIGRATION_CONFIG,
                script_location=self.MIGRATION_PATH,
            ),
        )


@dataclass
class AppSettings:
    """Application configuration."""

    NAME: str = field(default_factory=get_env("APP_NAME", "PURE ERP API"))
    """Application name."""
    DEBUG: bool = field(default_factory=get_env("LITESTAR_DEBUG", False))
    """Run `Litestar` with `debug=True`."""
    API_PREFIX: str = field(default_factory=get_env("API_PREFIX", "/api"))
    """Path prefix for every route. The frontend's API_BASE_URL points here."""
    SECRET_KEY: str = field(
        default_factory=get_env("SECRET_KEY", binascii.hexlify(os.urandom(32)).decode(encoding="utf-8")),
    )
    """Secret used to sign JWTs. Must be set in production, or tokens break on every restart."""
    JWT_ENCRYPTION_ALGORITHM: str = "HS256"
    """JWT Algorithm to use."""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = field(default_factory=get_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    """Lifetime of the access token cookie."""
    REFRESH_TOKEN_EXPIRE_DAYS: int = field(default_factory=get_env("REFRESH_TOKEN_EXPIRE_DAYS", 7))
    """Lifetime of the refresh token cookie."""
    ALLOWED_CORS_ORIGINS: list[str] | str = field(
        default_factory=get_env("ALLOWED_CORS_ORIGINS", ["http://localhost:5173"], list[str])
    )
    """Allowed CORS origins. Cookies are sent cross-origin, so `*` is not allowed."""
    COOKIE_SECURE: bool = field(default_factory=get_env("COOKIE_SECURE", False))
    """Use secure cookies (set to True in production with HTTPS)."""
    COOKIE_DOMAIN: str | None = field(default_factory=get_env("COOKIE_DOMAIN", None))
    """Optional cookie domain, e.g. `.example.com` when API and app are on sibling subdomains."""

    def get_cors_config(self) -> CORSConfig:
        return CORSConfig(
            allow_origins=cast("list[str]", self.ALLOWED_CORS_ORIGINS),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    def __post_init__(self) -> None:
        if isinstance(self.ALLOWED_CORS_ORIGINS, str):
            if self.ALLOWED_CORS_ORIGINS.startswith("[") and self.ALLOWED_CORS_ORIGINS.endswith("]"):
                try:
                    self.ALLOWED_CORS_ORIGINS = json.loads(self.ALLOWED_CORS_ORIGINS)
                except (SyntaxError, ValueError):
                    msg = "ALLOWED_CORS_ORIGINS is not a valid list representation."
                    raise ValueError(msg) from None
            else:
                self.ALLOWED_CORS_ORIGINS = [host.strip() for host in self.ALLOWED_CORS_ORIGINS.split(",")]
        if "*" in self.ALLOWED_CORS_ORIGINS:
            msg = "ALLOWED_CORS_ORIGINS cannot contain '*' because auth cookies are sent with credentials."
            raise ValueError(msg)


@dataclass
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    db: DatabaseSettings = field(default_factory=DatabaseSettings)

    @classmethod
    def from_env(cls, dotenv_filename: str = ".env") -> Settings:
        env_file = Path(f"{os.curdir}/{dotenv_filename}")
        if env_file.is_file():
            load_dotenv(env_file, override=False)
        return Settings()


@lru_cache(maxsize=1, typed=True)
def get_settings() -> Settings:
    return Settings.from_env()


def provide_app_settings() -> AppSettings:
    return get_settings().app
