"""Builds the client report snapshot.

This is the one place in the console where data leaves for an audience that
cannot see the console. Three rules follow from that, and each is enforced here
rather than trusted to the caller:

**One tenant, named by the token.** Every query is filtered on the tenant the
caller is scoped to. There is no tenant parameter reaching this module.

**Internal comments never appear.** A report is a client-facing document. Only
`visibility='client'` commentary is eligible, and even then it is counted rather
than quoted unless an analyst put it in the covering note deliberately.

**Nothing is inferred that the data does not support.** A tenant with no SLA
policy gets no SLA section, not a section full of zeroes that reads as perfect
performance.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents import sla
from app.models import Agent, Alert, Incident, IncidentComment, Tenant, TenantSla
from app.models.incident import CLOSED_STATUSES, OPEN_STATUSES

# The report names the worst handful rather than listing everything. A client
# reading forty rule IDs learns less than one reading five.
TOP_N = 8
NOTABLE_N = 10
CRITICAL = 13


@dataclass
class Period:
    start: datetime
    end: datetime


def _in_period(stmt: Select, column, period: Period) -> Select:
    return stmt.where(column >= period.start, column < period.end)


async def _alert_figures(
    session: AsyncSession, tenant_id: uuid.UUID, period: Period
) -> dict:
    total, first, last = (
        await session.execute(
            _in_period(
                select(func.count(), func.min(Alert.timestamp), func.max(Alert.timestamp))
                .where(Alert.tenant_id == tenant_id),
                Alert.timestamp,
                period,
            )
        )
    ).one()

    by_rule = (
        await session.execute(
            _in_period(
                select(
                    Alert.rule_id,
                    func.min(Alert.rule_desc).label("description"),
                    func.max(Alert.rule_level).label("level"),
                    func.count().label("count"),
                ).where(Alert.tenant_id == tenant_id),
                Alert.timestamp,
                period,
            )
            .group_by(Alert.rule_id)
            .order_by(func.count().desc())
            .limit(TOP_N)
        )
    ).all()

    techniques = (
        await session.execute(
            _in_period(
                select(
                    func.unnest(Alert.mitre_ids).label("technique"),
                    func.count().label("count"),
                ).where(Alert.tenant_id == tenant_id),
                Alert.timestamp,
                period,
            )
            .group_by(func.unnest(Alert.mitre_ids))
            .order_by(func.count().desc())
            .limit(TOP_N)
        )
    ).all()

    return {
        "total": total,
        "first_at": first.isoformat() if first else None,
        "last_at": last.isoformat() if last else None,
        "top_rules": [
            {
                "rule_id": row.rule_id,
                "description": row.description,
                "level": row.level,
                "count": row.count,
            }
            for row in by_rule
        ],
        "top_techniques": [
            {"technique_id": row.technique, "count": row.count} for row in techniques
        ],
    }


def _sla_section(policy: list[TenantSla], incidents: list[Incident], now: datetime) -> dict:
    """SLA performance over the period.

    A tenant with no policy gets `configured: false` and no figures. Reporting
    "0 breaches" against a contract that does not exist would read as perfect
    performance to a client who is paying for one.

    Breach is derived through `incidents.sla`, the same helpers the queue and the
    overview use. A second implementation here would eventually disagree with the
    console in front of a client, which is the worst place to find out.
    """
    if not policy:
        return {"configured": False}

    measured = [i for i in incidents if i.sla_respond_by is not None]
    responded = [i for i in measured if i.first_response_at is not None]
    response_breached = [i for i in measured if sla.response_breached(i, now=now)]
    resolvable = [i for i in incidents if i.sla_resolve_by is not None]
    resolution_breached = [i for i in resolvable if sla.resolution_breached(i, now=now)]

    minutes = [
        (i.first_response_at - i.first_seen).total_seconds() / 60 for i in responded
    ]
    held = sum(i.sla_paused_seconds or 0 for i in incidents)

    return {
        "configured": True,
        "bands": [
            {
                "severity_min": band.severity_min,
                "respond_minutes": band.respond_minutes,
                "resolve_minutes": band.resolve_minutes,
            }
            for band in policy
        ],
        "measured": len(measured),
        "responded": len(responded),
        "response_breached": len(response_breached),
        "resolution_measured": len(resolvable),
        "resolution_breached": len(resolution_breached),
        "response_met_pct": (
            round((len(measured) - len(response_breached)) / len(measured) * 100, 1)
            if measured
            else None
        ),
        "median_response_minutes": (
            round(sorted(minutes)[len(minutes) // 2], 1) if minutes else None
        ),
        # Time the clock was stopped awaiting the client. It belongs in the report
        # because it is the answer to "why did this take four days".
        "awaiting_client_hours": round(held / 3600, 1),
    }


async def build(
    session: AsyncSession,
    *,
    tenant: Tenant,
    period: Period,
    now: datetime,
) -> dict:
    """Compute the whole snapshot. Reads only; the caller persists it."""
    opened = list(
        await session.scalars(
            _in_period(
                select(Incident).where(Incident.tenant_id == tenant.id),
                Incident.created_at,
                period,
            )
        )
    )
    closed = list(
        await session.scalars(
            _in_period(
                select(Incident).where(
                    Incident.tenant_id == tenant.id,
                    Incident.status.in_(CLOSED_STATUSES),
                ),
                Incident.closed_at,
                period,
            )
        )
    )
    # Open *now*, regardless of when it was opened - a case carried in from last
    # month is still this month's outstanding work.
    still_open = list(
        await session.scalars(
            select(Incident).where(
                Incident.tenant_id == tenant.id, Incident.status.in_(OPEN_STATUSES)
            )
        )
    )

    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for incident in opened:
        if incident.severity >= CRITICAL:
            by_severity["critical"] += 1
        elif incident.severity >= 10:
            by_severity["high"] += 1
        elif incident.severity >= 7:
            by_severity["medium"] += 1
        else:
            by_severity["low"] += 1

    classifications: dict[str, int] = {}
    for incident in closed:
        key = incident.classification or "unclassified"
        classifications[key] = classifications.get(key, 0) + 1

    # Named individually because a client reads these, not the counts above.
    notable = sorted(
        opened, key=lambda i: (i.severity, i.alert_count), reverse=True
    )[:NOTABLE_N]

    client_comment_counts: dict[uuid.UUID, int] = {}
    if notable:
        client_comment_counts = dict(
            (
                await session.execute(
                    select(IncidentComment.incident_id, func.count())
                    .where(
                        IncidentComment.incident_id.in_([i.id for i in notable]),
                        # Internal commentary must never reach a client document.
                        IncidentComment.visibility == "client",
                    )
                    .group_by(IncidentComment.incident_id)
                )
            ).all()
        )

    agents = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Agent.status == "active"),
                func.count().filter(Agent.status == "disconnected"),
            ).where(Agent.tenant_id == tenant.id)
        )
    ).one()

    policy = await sla.policy_for(session, tenant.id)

    return {
        "schema": 1,
        "tenant": {"name": tenant.name, "slug": tenant.slug},
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "generated_at": now.isoformat(),
        "alerts": await _alert_figures(session, tenant.id, period),
        "incidents": {
            "opened": len(opened),
            "closed": len(closed),
            "still_open": len(still_open),
            "critical_opened": by_severity["critical"],
            "by_severity": by_severity,
            "by_classification": classifications,
            "false_positives": sum(
                1 for i in closed if i.status == "false_positive"
            ),
        },
        "sla": _sla_section(policy, opened, now),
        "notable_incidents": [
            {
                "number": incident.number,
                "title": incident.title,
                "severity": incident.severity,
                "status": incident.status,
                "classification": incident.classification,
                "alert_count": incident.alert_count,
                "first_seen": incident.first_seen.isoformat(),
                "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
                "response_breached": sla.response_breached(incident, now=now),
                "client_updates": client_comment_counts.get(incident.id, 0),
            }
            for incident in notable
        ],
        "coverage": {
            "agents_total": agents[0],
            "agents_active": agents[1],
            "agents_disconnected": agents[2],
            "alert_floor": tenant.alert_floor,
        },
    }
