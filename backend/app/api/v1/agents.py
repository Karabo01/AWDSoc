"""The agent fleet, read from cache.

Nothing in this router talks to a client's manager on the request path. A page
load must not depend on someone else's network being up, so every read comes from
the `agents` table and carries `synced_at` so staleness is visible rather than
implied. The only route that reaches out is the explicit sync, and it is staff
only and rate-limited by being manual.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.rbac import require_staff
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.models import Agent, Alert, Incident, Tenant, User
from app.models.incident import OPEN_STATUSES
from app.pagination import decode_cursor, encode_cursor
from app.schemas.agent import AgentDetail, AgentPage, AgentSummary, SyncReport
from app.schemas.alert import AlertPage, AlertSummary
from app.wazuh import sync as agent_sync

router = APIRouter(prefix="/agents", tags=["agents"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

MAX_PAGE = 500
NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such agent.")


async def _scoped(
    stmt: Select, session: AsyncSession, user: User, scope: TenantScope, column
) -> Select:
    stmt = scope.apply(stmt, column)
    if scope.is_fleet_view:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is not None:
            stmt = stmt.where(column.in_(allowed))
    return stmt


def _summarise(agent: Agent, tenant: Tenant | None) -> AgentSummary:
    payload = AgentSummary.model_validate(agent)
    if tenant is not None:
        payload.tenant_name = tenant.name
        payload.tenant_slug = tenant.slug
        payload.tenant_colour = tenant.colour
    return payload


@router.get("", response_model=AgentPage)
async def list_agents(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 200,
    status_: Annotated[str | None, Query(alias="status")] = None,
    group: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> AgentPage:
    """A fleet is hundreds of rows, not millions, and it has no natural time
    axis - so this one list is ordered by name and not cursor-paged. The cursor
    field stays on the response so the shape matches every other list."""
    stmt = select(Agent, Tenant).join(Tenant, Tenant.id == Agent.tenant_id)
    stmt = await _scoped(stmt, session, user, scope, Agent.tenant_id)

    if status_:
        stmt = stmt.where(Agent.status == status_)
    if group:
        stmt = stmt.where(Agent.groups.contains([group]))
    if q:
        stmt = stmt.where(Agent.name.ilike(f"%{q}%"))

    stmt = stmt.order_by(Agent.name.asc(), Agent.agent_id.asc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    return AgentPage(items=[_summarise(agent, tenant) for agent, tenant in rows])


@router.post("/sync", response_model=list[SyncReport], dependencies=[require_staff])
async def sync_agents(
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> list[SyncReport]:
    """Refresh the cache from the managers this token can already see.

    There is deliberately no `tenant_id` parameter. Naming a tenant here would be
    the caller choosing whose manager we connect to, which is exactly the thing
    tenancy-from-the-token exists to prevent - a `soc_analyst` narrowed by
    `staff_tenant_access` could otherwise reach a client they cannot read. To sync
    one client, switch to that client; the scope follows.

    This is the one route that reaches out over the network, and it can take as
    long as the slowest manager. It reports per tenant rather than failing as a
    whole: one unreachable client must not hide five successful syncs.
    """
    if scope.tenant_id is not None:
        results = await agent_sync.sync_all(session, tenant_id=scope.tenant_id)
    else:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is None:
            results = await agent_sync.sync_all(session)
        else:
            results = []
            for allowed_id in allowed:
                results.extend(await agent_sync.sync_all(session, tenant_id=allowed_id))

    slugs = {
        row.id: row.slug for row in (await session.execute(select(Tenant.id, Tenant.slug))).all()
    }
    await audit.record(
        session,
        action="agents.synced",
        target_type="tenant",
        target_id=scope.tenant_id,
        user_id=user.id,
        detail={
            "tenants": len(results),
            "failed": [str(r.tenant_id) for r in results if not r.ok],
        },
    )
    await session.commit()

    return [
        SyncReport(
            tenant_id=r.tenant_id,
            tenant_slug=slugs.get(r.tenant_id),
            ok=r.ok,
            synced=r.synced,
            removed=r.removed,
            error=r.error,
            warnings=r.warnings,
        )
        for r in results
    ]


@router.get("/{agent_id}/alerts", response_model=AlertPage)
async def agent_alerts(
    agent_id: str,
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> AlertPage:
    stmt = (
        select(Alert, Tenant)
        .join(Tenant, Tenant.id == Alert.tenant_id)
        .where(Alert.agent_id == agent_id)
    )
    stmt = await _scoped(stmt, session, user, scope, Alert.tenant_id)

    if cursor:
        last_timestamp, last_id = decode_cursor(cursor)
        stmt = stmt.where((Alert.timestamp, Alert.id) < (last_timestamp, last_id))

    stmt = stmt.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for alert, tenant in rows:
        summary = AlertSummary.model_validate(alert)
        summary.tenant_name = tenant.name
        summary.tenant_slug = tenant.slug
        summary.tenant_colour = tenant.colour
        items.append(summary)

    next_cursor = (
        encode_cursor(rows[-1][0].timestamp, rows[-1][0].id) if has_more and rows else None
    )
    return AlertPage(items=items, next_cursor=next_cursor)


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: str, user: CurrentUser, session: Session, scope: Scope
) -> AgentDetail:
    stmt = (
        select(Agent, Tenant)
        .join(Tenant, Tenant.id == Agent.tenant_id)
        .where(Agent.agent_id == agent_id)
    )
    stmt = await _scoped(stmt, session, user, scope, Agent.tenant_id)
    # A fleet view can match the same manager-assigned id under two tenants. That
    # is precisely the misgrouping case below, and it is reported rather than
    # arbitrated: take one row, then say plainly that there is more than one.
    rows = (await session.execute(stmt.order_by(Agent.synced_at.desc()))).all()
    if not rows:
        raise NOT_FOUND

    agent, tenant = rows[0]
    detail = AgentDetail.model_validate(agent)
    detail.tenant_name = tenant.name
    detail.tenant_slug = tenant.slug
    detail.tenant_colour = tenant.colour

    if len(rows) > 1:
        detail.misgrouped_with = sorted({t.slug for _, t in rows})

    since = datetime.now(UTC) - timedelta(hours=24)
    counts = (
        await session.execute(
            select(func.count(), func.max(Alert.timestamp)).where(
                Alert.tenant_id == agent.tenant_id,
                Alert.agent_id == agent_id,
                Alert.timestamp >= since,
            )
        )
    ).one()
    detail.alerts_24h = counts[0]
    detail.last_alert_at = counts[1]

    # Bounded to 30 days on purpose. `alerts` is partitioned by timestamp, and an
    # unbounded count here would touch every partition the table has ever had.
    detail.open_incidents = (
        await session.scalar(
            select(func.count(func.distinct(Alert.incident_id)))
            .join(Incident, Incident.id == Alert.incident_id)
            .where(
                Alert.tenant_id == agent.tenant_id,
                Alert.agent_id == agent_id,
                Alert.timestamp >= datetime.now(UTC) - timedelta(days=30),
                Incident.status.in_(OPEN_STATUSES),
            )
        )
        or 0
    )
    return detail
