from __future__ import annotations

import asyncio
import hashlib
import secrets

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

hasher = PasswordHash((Argon2Hasher(),))


async def get_password_hash(password: str | bytes) -> str:
    """Hash a password with Argon2 in a worker thread."""
    return await asyncio.get_running_loop().run_in_executor(None, hasher.hash, password)


async def verify_password(plain_password: str | bytes, hashed_password: str) -> bool:
    """Check a plain password against its stored hash."""
    valid, _ = await asyncio.get_running_loop().run_in_executor(
        None,
        hasher.verify_and_update,
        plain_password,
        hashed_password,
    )
    return bool(valid)


def generate_token() -> str:
    """Random URL-safe token for refresh cookies."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a token. Only hashes are stored in the database."""
    return hashlib.sha256(token.encode()).hexdigest()
