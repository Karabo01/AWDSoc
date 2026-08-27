"""Password hashing and JWT minting.

Tenant scoping is derived from the token and nowhere else. A client user's token
carries a fixed `tenant_id`. A staff token carries `is_staff: true` plus an
`active_tenant` that is either a tenant UUID or null meaning all-tenants.
Switching tenants issues a new token; no endpoint accepts a tenant parameter.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()  # argon2id defaults

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    is_staff: bool
    tenant_id: uuid.UUID | None  # client users only
    active_tenant: uuid.UUID | None  # staff only; None means all tenants
    token_type: TokenType
    jti: str
    expires_at: datetime

    @property
    def scope_tenant_id(self) -> uuid.UUID | None:
        """The tenant every query must filter on, or None for a fleet view."""
        return self.tenant_id if not self.is_staff else self.active_tenant


def _encode(
    *,
    user_id: uuid.UUID,
    role: str,
    is_staff: bool,
    tenant_id: uuid.UUID | None,
    active_tenant: uuid.UUID | None,
    token_type: TokenType,
    ttl: int,
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl)
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": settings.app_name,
        "typ": token_type,
        "role": role,
        "is_staff": is_staff,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "active_tenant": str(active_tenant) if active_tenant else None,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


def issue_access_token(
    *,
    user_id: uuid.UUID,
    role: str,
    is_staff: bool,
    tenant_id: uuid.UUID | None,
    active_tenant: uuid.UUID | None = None,
) -> tuple[str, datetime]:
    token, _, expires_at = _encode(
        user_id=user_id,
        role=role,
        is_staff=is_staff,
        tenant_id=tenant_id,
        active_tenant=active_tenant,
        token_type="access",
        ttl=settings.jwt_access_ttl,
    )
    return token, expires_at


def issue_refresh_token(
    *,
    user_id: uuid.UUID,
    role: str,
    is_staff: bool,
    tenant_id: uuid.UUID | None,
    active_tenant: uuid.UUID | None = None,
) -> tuple[str, str, datetime]:
    return _encode(
        user_id=user_id,
        role=role,
        is_staff=is_staff,
        tenant_id=tenant_id,
        active_tenant=active_tenant,
        token_type="refresh",
        ttl=settings.jwt_refresh_ttl,
    )


class TokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"expected a {expected_type} token")

    def as_uuid(value: Any) -> uuid.UUID | None:
        return uuid.UUID(value) if value else None

    try:
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            role=payload["role"],
            is_staff=bool(payload["is_staff"]),
            tenant_id=as_uuid(payload.get("tenant_id")),
            active_tenant=as_uuid(payload.get("active_tenant")),
            token_type=expected_type,
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed token claims") from exc
