"""Ingest authentication. This is the trust boundary.

Four protections, all required, per DESIGN.md §3:

1. Tenant slug in the path - tenancy is never inferred from the payload.
2. HMAC-SHA256 over "<timestamp>.<raw body>", keyed with that tenant's secret.
3. A 300-second replay window on X-AWD-Timestamp.
4. A per-tenant source IP allowlist.

**Uniform failure is a requirement, not a nicety.** An unknown slug, a bad
signature, a stale timestamp and a disallowed IP must all cost the same work and
return the same 401, or the endpoint becomes a tenant enumeration oracle. So this
module never returns early: it computes every check, always performs one HMAC
(against a dummy secret when the tenant is unknown), and decides at the end.
"""

import hashlib
import hmac
import ipaddress
import logging
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import SessionLocal
from app.models import Tenant

log = logging.getLogger(__name__)

SIGNATURE_PREFIX = "sha256="
# Used only to keep the unknown-tenant path the same cost as the known one.
_DUMMY_SECRET = "not-a-real-tenant-secret-only-here-to-equalise-timing"


class Rejection(StrEnum):
    UNKNOWN_TENANT = "unknown_tenant"
    TENANT_INACTIVE = "tenant_inactive"
    BAD_SIGNATURE = "bad_signature"
    MALFORMED_SIGNATURE = "malformed_signature"
    STALE_TIMESTAMP = "stale_timestamp"
    DISALLOWED_IP = "disallowed_ip"
    # Postgres is down and this slug was never cached, so we cannot decide.
    LOOKUP_UNAVAILABLE = "lookup_unavailable"


@dataclass(frozen=True)
class CachedTenant:
    """Only what ingest needs. Deliberately not the ORM object - the hot path
    must not hold a session-bound instance."""

    id: uuid.UUID
    slug: str
    secret: str
    status: str
    cidrs: tuple[str, ...]


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    tenant: CachedTenant | None = None
    reason: Rejection | None = None


class TenantAuthCache:
    """Slug -> auth material, with stale-on-error.

    A rotated secret propagates within `tenant_cache_soft_ttl`. That is
    acceptable because rotation already breaks delivery until the client's
    manager is reinstalled - a few extra seconds changes nothing.
    """

    def __init__(self) -> None:
        # slug -> (tenant or None, fetched_at)
        self._entries: dict[str, tuple[CachedTenant | None, float]] = {}

    def invalidate(self, slug: str | None = None) -> None:
        if slug is None:
            self._entries.clear()
        else:
            self._entries.pop(slug, None)

    async def get(self, slug: str) -> CachedTenant | None:
        now = time.monotonic()
        cached = self._entries.get(slug)

        if cached is not None:
            tenant, fetched_at = cached
            age = now - fetched_at
            ttl = (
                settings.tenant_cache_negative_ttl
                if tenant is None
                else settings.tenant_cache_soft_ttl
            )
            if age < ttl:
                return tenant
            if age > settings.tenant_cache_hard_ttl:
                self._entries.pop(slug, None)
                cached = None

        try:
            tenant = await self._load(slug)
        except (SQLAlchemyError, OSError):
            if cached is not None:
                # Postgres is degraded. Ingestion must keep buffering, so serve
                # the stale entry and try again on the next request.
                log.warning("tenant lookup failed for %s; serving stale auth", slug)
                return cached[0]
            log.error("tenant lookup failed for %s and nothing cached", slug)
            raise

        self._entries[slug] = (tenant, now)
        return tenant

    @staticmethod
    async def _load(slug: str) -> CachedTenant | None:
        async with SessionLocal() as session:
            tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
            if tenant is None:
                return None
            return CachedTenant(
                id=tenant.id,
                slug=tenant.slug,
                secret=tenant.ingest_secret,
                status=tenant.status,
                cidrs=tuple(str(c) for c in (tenant.ingest_cidrs or [])),
            )


tenant_cache = TenantAuthCache()


def expected_signature(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over "<timestamp>.<body>", hex.

    Must match `sign()` in deploy/wazuh/custom-awd-console byte for byte. The
    timestamp is inside the signed material so a captured body cannot be replayed
    under a fresh header.
    """
    material = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), material, hashlib.sha256).hexdigest()


def _signature_matches(secret: str, timestamp: str, body: bytes, presented: str) -> bool:
    return hmac.compare_digest(expected_signature(secret, timestamp, body), presented)


def timestamp_is_fresh(raw: str, *, now: float | None = None) -> bool:
    try:
        sent = int(raw)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    # Symmetric: a clock ahead of ours is as suspicious as one behind.
    return abs(now - sent) <= settings.ingest_max_skew_seconds


def ip_is_allowed(source_ip: str | None, cidrs: tuple[str, ...]) -> bool:
    """An empty allowlist means any source. Each client's manager has a different
    egress address, which is why this is per-tenant data and not an env var."""
    if not cidrs:
        return True
    if source_ip is None:
        return False
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            log.warning("tenant has an unparseable ingest CIDR: %r", cidr)
    return False


def client_ip(forwarded_for: str | None, peer: str | None) -> str | None:
    """Traefik appends the real peer to X-Forwarded-For, so the trustworthy entry
    is counted from the right. Taking the leftmost would let a client spoof its
    own source address and defeat the allowlist entirely."""
    if not forwarded_for:
        return peer
    hops = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if not hops:
        return peer
    index = len(hops) - settings.ingest_trusted_proxy_hops
    return hops[max(index, 0)]


async def authenticate(
    *,
    slug: str,
    body: bytes,
    signature_header: str | None,
    timestamp_header: str | None,
    source_ip: str | None,
) -> AuthResult:
    """Verify an ingest request. Constant-shaped: every branch does one HMAC."""
    reason: Rejection | None = None

    try:
        tenant = await tenant_cache.get(slug)
    except (SQLAlchemyError, OSError):
        # Fail closed, but tell the caller to retry rather than give up: the
        # integrator retries 5xx and abandons 4xx, so a 401 here would silently
        # discard a legitimate client's alert.
        tenant = None
        reason = Rejection.LOOKUP_UNAVAILABLE

    presented = signature_header or ""
    if presented.startswith(SIGNATURE_PREFIX):
        presented = presented[len(SIGNATURE_PREFIX) :]
    else:
        reason = reason or Rejection.MALFORMED_SIGNATURE

    timestamp = timestamp_header or ""
    if not timestamp_is_fresh(timestamp):
        reason = reason or Rejection.STALE_TIMESTAMP

    # Always exactly one HMAC, whether or not the tenant exists.
    secret = tenant.secret if tenant is not None else _DUMMY_SECRET
    signature_ok = _signature_matches(secret, timestamp, body, presented)

    if reason is Rejection.LOOKUP_UNAVAILABLE:
        pass  # already decided; the HMAC above kept the timing uniform
    elif tenant is None:
        reason = reason or Rejection.UNKNOWN_TENANT
    elif not signature_ok:
        reason = reason or Rejection.BAD_SIGNATURE
    elif not ip_is_allowed(source_ip, tenant.cidrs):
        reason = reason or Rejection.DISALLOWED_IP
    elif tenant.status != "active":
        reason = reason or Rejection.TENANT_INACTIVE

    if reason is not None:
        return AuthResult(ok=False, reason=reason)
    return AuthResult(ok=True, tenant=tenant)
