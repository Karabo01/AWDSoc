"""The landing page, for one client or for the whole fleet.

Breach counts are computed in Python by calling `incidents.sla` on the loaded
rows rather than being reimplemented as a SQL predicate. The five clock rules are
subtle enough - especially "a pause cannot un-breach something already breached" -
that a second implementation would drift from the first, and the queue and the
overview would then disagree about the same case in front of a client.

That is affordable because the set is bounded: only *open* incidents are loaded,
and an open queue is hundreds of rows on an MSSP, not millions. Closed cases
never enter the calculation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.incidents import sla
from app.models import Agent, Alert, Incident, Tenant, TenantSla, WazuhConnection
from app.models.incident import OPEN_STATUSES
from app.schemas.overview import MisgroupedAgent, Overview, TenantOverview
from app.wazuh.sync import misgrouped_agents

router = APIRouter(tags=["overview"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

CRITICAL = 13
# A response deadline inside this window is worth surfacing before it is missed.
AT_RISK_WINDOW = timedelta(hours=1)
SILENT_AFTER = timedelta(hours=24)


@router.get("/overview", response_model=Overview)
async def overview(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> Overview:
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)

    # Which tenants this token may see, resolved once and applied to every query
    # below. There is no path here that reads a tenant the caller cannot name.
    if scope.tenant_id is not None:
        visible: list[uuid.UUID] | None = [scope.tenant_id]
    else:
        visible = await accessible_tenant_ids(session, user)

    tenant_stmt = select(Tenant).order_by(Tenant.name)
    if visible is not None:
        tenant_stmt = tenant_stmt.where(Tenant.id.in_(visible))
    tenants = list(await session.scalars(tenant_stmt))

    report = Overview(scope="fleet" if scope.is_fleet_view else "tenant", generated_at=now)
    if not tenants:
        return report

    ids = [tenant.id for tenant in tenants]
    rows = {
        tenant.id: TenantOverview(
            tenant_id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            colour=tenant.colour,
            status=tenant.status,
        )
        for tenant in tenants
    }

    # --- incidents ---------------------------------------------------------
    incidents = list(
        await session.scalars(
            select(Incident).where(Incident.tenant_id.in_(ids), Incident.status.in_(OPEN_STATUSES))
        )
    )
    for incident in incidents:
        row = rows.get(incident.tenant_id)
        if row is None:
            continue
        row.open_incidents += 1
        if incident.status == "new":
            row.new_incidents += 1
        if incident.status == sla.PAUSED_STATUS:
            row.awaiting_client += 1
        if incident.assignee_id is None:
            row.unassigned_incidents += 1
        if incident.severity >= CRITICAL:
            row.critical_open += 1

        breached = sla.response_breached(incident, now=now)
        if breached:
            row.response_breached += 1
        if sla.resolution_breached(incident, now=now):
            row.resolution_breached += 1
        if (
            not breached
            and incident.sla_respond_by is not None
            and incident.first_response_at is None
            and incident.sla_paused_at is None
            and incident.sla_respond_by - now <= AT_RISK_WINDOW
        ):
            row.at_risk += 1

    # --- alerts ------------------------------------------------------------
    alert_rows = await session.execute(
        select(Alert.tenant_id, func.count(), func.max(Alert.timestamp))
        .where(Alert.tenant_id.in_(ids), Alert.timestamp >= since)
        .group_by(Alert.tenant_id)
    )
    for tenant_id, count, last_alert in alert_rows.all():
        row = rows.get(tenant_id)
        if row is not None:
            row.alerts_24h = count
            row.last_alert_at = last_alert

    # A tenant with no alerts in the window may still have delivered before it,
    # so `last_alert_at` is filled from the whole history when the window is dry.
    quiet = [tid for tid, row in rows.items() if row.last_alert_at is None]
    if quiet:
        # Unbounded in time, but one row per tenant and driven by
        # `alerts_tenant_ts_idx`, so it is an index scan per partition, not a read.
        history = await session.execute(
            select(Alert.tenant_id, func.max(Alert.timestamp))
            .where(Alert.tenant_id.in_(quiet))
            .group_by(Alert.tenant_id)
        )
        for tenant_id, last_alert in history.all():
            rows[tenant_id].last_alert_at = last_alert

    for row in rows.values():
        row.silent = row.last_alert_at is None or (now - row.last_alert_at) > SILENT_AFTER

    # --- agents ------------------------------------------------------------
    agent_rows = await session.execute(
        select(
            Agent.tenant_id,
            func.count(),
            func.count().filter(Agent.status == "active"),
            func.count().filter(Agent.status == "disconnected"),
        )
        .where(Agent.tenant_id.in_(ids))
        .group_by(Agent.tenant_id)
    )
    for tenant_id, total, active, disconnected in agent_rows.all():
        row = rows.get(tenant_id)
        if row is not None:
            row.agents_total = total
            row.agents_active = active
            row.agents_disconnected = disconnected

    # --- onboarding completeness -------------------------------------------
    connections = await session.execute(
        select(
            WazuhConnection.tenant_id,
            WazuhConnection.last_sync_at,
            WazuhConnection.last_sync_error,
        ).where(WazuhConnection.tenant_id.in_(ids))
    )
    for tenant_id, last_sync_at, last_sync_error in connections.all():
        row = rows.get(tenant_id)
        if row is not None:
            row.has_connection = True
            row.last_sync_at = last_sync_at
            row.last_sync_error = last_sync_error

    with_sla = set(
        await session.scalars(
            select(TenantSla.tenant_id).where(TenantSla.tenant_id.in_(ids)).distinct()
        )
    )
    for tenant_id in with_sla:
        if tenant_id in rows:
            rows[tenant_id].has_sla = True

    # --- roll-up -----------------------------------------------------------
    report.tenants = [rows[tenant.id] for tenant in tenants]
    for row in report.tenants:
        report.open_incidents += row.open_incidents
        report.critical_open += row.critical_open
        report.response_breached += row.response_breached
        report.at_risk += row.at_risk
        report.alerts_24h += row.alerts_24h
    report.silent_tenants = [row.slug for row in report.tenants if row.silent]

    # Staff only: naming another tenant to a client token would itself be a leak.
    if user.is_staff:
        report.misgrouped_agents = [
            MisgroupedAgent(**item) for item in await misgrouped_agents(session)
        ]

    return report
