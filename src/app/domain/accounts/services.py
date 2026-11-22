from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from advanced_alchemy.extensions.litestar import repository, service
from litestar.exceptions import NotAuthorizedException
from sqlalchemy.orm import undefer

from app.db import models as m
from app.lib import crypt

if TYPE_CHECKING:
    from uuid import UUID


class UserService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    """Handles database operations for users."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.User]):
        model_type = m.User

    repository_type = Repo
    match_fields = ["email"]

    async def to_model_on_create(self, data: service.ModelDictT[m.User]) -> service.ModelDictT[m.User]:
        return await self._hash_password(data)

    async def to_model_on_update(self, data: service.ModelDictT[m.User]) -> service.ModelDictT[m.User]:
        return await self._hash_password(data)

    async def _hash_password(self, data: service.ModelDictT[m.User]) -> service.ModelDictT[m.User]:
        if service.is_dict(data) and (password := data.pop("password", None)) is not None:
            data["hashed_password"] = await crypt.get_password_hash(password)
        return data

    async def authenticate(self, email: str, password: str) -> m.User:
        """Check credentials. Every failure gives the same message so emails can't be probed."""
        invalid = NotAuthorizedException(detail="Email or password is incorrect")
        user = await self.get_one_or_none(m.User.email == email, load=[undefer(m.User.hashed_password)])
        if user is None or user.hashed_password is None:
            # hash anyway so a missing account takes as long as a wrong password
            await crypt.get_password_hash(password)
            raise invalid
        if not await crypt.verify_password(password, user.hashed_password):
            raise invalid
        if not user.is_active:
            raise NotAuthorizedException(detail="This account is inactive. Ask an administrator to activate it.")
        return user

    async def touch_last_active(self, user: m.User) -> None:
        await self.update({"last_active_at": datetime.now(UTC)}, item_id=user.id)


class RoleService(service.SQLAlchemyAsyncRepositoryService[m.Role]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.Role]):
        model_type = m.Role

    repository_type = Repo
    match_fields = ["name"]


class RefreshTokenService(service.SQLAlchemyAsyncRepositoryService[m.RefreshToken]):
    """Refresh token rotation with reuse detection (adapted from the fullstack template)."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.RefreshToken]):
        model_type = m.RefreshToken

    repository_type = Repo
    match_fields = ["token_hash"]

    async def create_refresh_token(
        self,
        user_id: UUID,
        expiration_days: int,
        family_id: UUID | None = None,
        device_info: str | None = None,
    ) -> tuple[str, m.RefreshToken]:
        """Returns the raw token (sent to the client once) and the stored row (hash only)."""
        raw_token = crypt.generate_token()
        created = await self.create(
            {
                "user_id": user_id,
                "token_hash": crypt.hash_token(raw_token),
                "family_id": family_id or uuid4(),
                "expires_at": m.RefreshToken.create_expires_at(days=expiration_days),
                "device_info": device_info,
            }
        )
        return raw_token, created

    async def rotate_refresh_token(
        self, raw_token: str, expiration_days: int, device_info: str | None = None
    ) -> tuple[str, m.RefreshToken]:
        """Revoke the presented token and issue a new one in the same family.

        Presenting an already revoked token means it was stolen or replayed, so the whole family is revoked.
        """
        old_token = await self.get_one_or_none(token_hash=crypt.hash_token(raw_token))
        if old_token is None:
            raise NotAuthorizedException(detail="Session not found. Sign in again.")
        if old_token.is_revoked:
            await self.revoke_token_family(old_token.family_id)
            raise NotAuthorizedException(detail="Session was revoked. Sign in again.")
        if old_token.is_expired:
            raise NotAuthorizedException(detail="Session expired. Sign in again.")

        await self.update({"revoked_at": datetime.now(UTC)}, item_id=old_token.id)
        return await self.create_refresh_token(
            user_id=old_token.user_id,
            expiration_days=expiration_days,
            family_id=old_token.family_id,
            device_info=device_info or old_token.device_info,
        )

    async def revoke_token_family(self, family_id: UUID) -> int:
        return await self._revoke(m.RefreshToken.family_id == family_id)

    async def revoke_user_tokens(self, user_id: UUID) -> int:
        """Sign a user out everywhere, e.g. after a password change or deactivation."""
        return await self._revoke(m.RefreshToken.user_id == user_id)

    async def revoke_raw_token(self, raw_token: str) -> None:
        if token := await self.get_one_or_none(token_hash=crypt.hash_token(raw_token)):
            await self.revoke_token_family(token.family_id)

    async def _revoke(self, *filters: Any) -> int:
        tokens = await self.get_many(*filters, m.RefreshToken.revoked_at.is_(None))
        now = datetime.now(UTC)
        for token in tokens:
            token.revoked_at = now
        if tokens:
            # committed immediately: revocation often happens right before a 401, which rolls the request back
            await self.update_many(tokens, auto_commit=True)
        return len(tokens)
