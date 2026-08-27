"""Rule read-through.

Wazuh rule definitions live on the client's manager, not here. Copying the whole
ruleset into our database would mean maintaining a second copy of something the
client can change at any moment, so this reads through on demand and caches for
an hour.

Two properties matter more than freshness:

**A slow manager must not become a slow console.** The client has a short timeout
and any failure degrades to a cached copy, or to the rule id and nothing else.
The case view still renders.

**The cache is keyed per tenant.** Two clients running different rulesets can
disagree about what rule 100200 is, and serving one client's local rule text to
another would be a small but real leak.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.models import Alert, Tenant, WazuhConnection
from app.redis_client import get_redis
from app.schemas.agent import RuleRead
from app.wazuh.manager_client import ManagerError, WazuhManagerClient

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["rules"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

CACHE_TTL = 3600
# A stale copy is served for a day beyond its TTL when the manager is unreachable.
# An analyst reading a rule description does not need it to be an hour fresh; they
# need it to be there.
STALE_TTL = 86_400


def _cache_key(tenant_id, rule_id: int) -> str:
    return f"{settings.app_name}:rule:{tenant_id}:{rule_id}"


def _from_manager(rule_id: int, item: dict) -> RuleRead:
    """Flatten the manager's shape. Compliance mappings arrive under different
    keys depending on the Wazuh version, so each is read defensively."""

    def as_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str) and value:
            return [value]
        return []

    mitre = item.get("mitre") if isinstance(item.get("mitre"), dict) else {}
    compliance = item.get("compliance") if isinstance(item.get("compliance"), dict) else {}

    def compliance_key(name: str) -> list[str]:
        return as_list(item.get(name) or compliance.get(name))

    return RuleRead(
        id=rule_id,
        level=item.get("level"),
        description=item.get("description"),
        groups=as_list(item.get("groups")),
        mitre_ids=as_list(mitre.get("id")),
        pci_dss=compliance_key("pci_dss"),
        gdpr=compliance_key("gdpr"),
        hipaa=compliance_key("hipaa"),
        nist_800_53=compliance_key("nist_800_53"),
        filename=item.get("filename"),
        relative_dirname=item.get("relative_dirname"),
        cached_at=datetime.now(UTC),
    )


async def _resolve_tenant(session: AsyncSession, user, scope: TenantScope) -> Tenant | None:
    """Which manager to ask. A client token names exactly one.

    A staff fleet view has no single manager to consult, so it gets the fallback
    below rather than an arbitrary tenant's answer. Opening the case first - which
    is how an analyst reaches a rule in practice - switches them to that tenant.
    """
    if scope.tenant_id is not None:
        return await session.get(Tenant, scope.tenant_id)
    allowed = await accessible_tenant_ids(session, user)
    if allowed is not None and len(allowed) == 1:
        return await session.get(Tenant, allowed[0])
    return None


@router.get("/{rule_id}", response_model=RuleRead)
async def get_rule(rule_id: int, user: CurrentUser, session: Session, scope: Scope) -> RuleRead:
    tenant = await _resolve_tenant(session, user, scope)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rule text comes from one client's manager. Switch to a client "
            "first, or open the rule from an incident.",
        )

    redis = get_redis()
    key = _cache_key(tenant.id, rule_id)

    cached = None
    try:
        raw = await redis.get(key)
        cached = RuleRead.model_validate(json.loads(raw)) if raw else None
    except Exception:  # noqa: BLE001 - a cache miss and a broken cache are the same
        log.warning("rule cache read failed", exc_info=True)

    if cached is not None and not cached.stale:
        return cached

    connection = await session.get(WazuhConnection, tenant.id)
    if connection is None:
        return await _fallback(session, tenant, rule_id, cached)

    try:
        async with WazuhManagerClient(connection) as client:
            item = await client.rule(rule_id)
    except ManagerError as exc:
        log.info("rule %s unavailable for %s: %s", rule_id, tenant.slug, exc)
        return await _fallback(session, tenant, rule_id, cached)

    if item is None:
        return await _fallback(session, tenant, rule_id, cached)

    rule = _from_manager(rule_id, item)
    try:
        await redis.set(key, rule.model_dump_json(), ex=CACHE_TTL)
        # A second copy under a longer TTL is what makes the degraded path above
        # possible: the fresh key expires, this one survives to be served stale.
        await redis.set(f"{key}:stale", rule.model_dump_json(), ex=STALE_TTL)
    except Exception:  # noqa: BLE001 - caching is an optimisation, not a contract
        log.warning("rule cache write failed", exc_info=True)
    return rule


async def _fallback(
    session: AsyncSession, tenant: Tenant, rule_id: int, cached: RuleRead | None
) -> RuleRead:
    """When the manager cannot answer: a stale copy, then what our own alerts
    have recorded about this rule, then just the id."""
    if cached is not None:
        cached.stale = True
        return cached

    try:
        raw = await get_redis().get(f"{_cache_key(tenant.id, rule_id)}:stale")
        if raw:
            rule = RuleRead.model_validate(json.loads(raw))
            rule.stale = True
            return rule
    except Exception:  # noqa: BLE001
        log.warning("stale rule cache read failed", exc_info=True)

    # Every alert carries the rule's level, description and groups as the manager
    # sent them at detection time. That is a genuine, if narrow, answer.
    row = (
        await session.execute(
            select(Alert.rule_level, Alert.rule_desc, Alert.rule_groups, Alert.mitre_ids)
            .where(Alert.tenant_id == tenant.id, Alert.rule_id == rule_id)
            .order_by(Alert.timestamp.desc())
            .limit(1)
        )
    ).first()

    if row is None:
        return RuleRead(id=rule_id, stale=True)
    return RuleRead(
        id=rule_id,
        level=row[0],
        description=row[1],
        groups=list(row[2] or []),
        mitre_ids=list(row[3] or []),
        stale=True,
    )
