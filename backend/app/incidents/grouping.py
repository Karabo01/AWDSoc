"""Incident fingerprinting.

Deliberately coarse. Coarse grouping produces fewer, fatter incidents, which is
the right failure mode for an MSSP: an analyst covering six clients would rather
open one incident with forty alerts than forty incidents.

`tenant_id` is inside the hash, so two clients can never share an incident even
if every other component matches.

M3 computes this with an empty `primary_entity`, because resolving one requires
the normalised document that M4 produces. Reprocessing recomputes it, which is
safe while no incidents exist yet - and is the reason M5 must not start before
M4's replay has run.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents import evidence, sla
from app.models import Incident, TenantCounter, TenantSla
from app.models.incident import CLOSED_STATUSES, OPEN_STATUSES

# "This recurred" only makes sense for a while.
RELATED_LOOKBACK_DAYS = 7


@dataclass
class AlertFacts:
    """Everything grouping needs from one alert, decoupled from the ORM row so
    the same logic serves ingest and any future backfill."""

    tenant_id: uuid.UUID
    timestamp: datetime
    rule_id: int
    rule_level: int
    rule_desc: str
    fingerprint: str
    ecs: dict = field(default_factory=dict)
    related: dict = field(default_factory=dict)
    primary_entity: str = ""


def fingerprint(
    *,
    tenant_id: uuid.UUID | str,
    rule_id: int,
    agent_id: str | None,
    primary_entity: str = "",
) -> str:
    material = f"{tenant_id}|{rule_id}|{agent_id or ''}|{primary_entity}"
    return hashlib.sha256(material.encode()).hexdigest()


def primary_entity(ecs: dict) -> str:
    """First match wins: source.ip -> user.name -> host.name -> "".

    Reads the normalised document, never the raw alert - that is what keeps the
    fingerprint stable across Wazuh versions and decoder changes.
    """
    for path in ("source.ip", "user.name", "host.name"):
        value = ecs.get(path)
        if isinstance(value, dict | list):
            continue
        if value not in (None, ""):
            return str(value)
    return ""


# --- attach or create ---------------------------------------------------------

MAX_TITLE = 200


async def next_incident_number(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Atomic per-tenant counter.

    `max(number) + 1` races: two alerts landing together read the same maximum
    and one loses to the unique constraint. The row lock here serialises exactly
    the writers that need it, per tenant, without touching anyone else.
    """
    statement = (
        insert(TenantCounter)
        .values(tenant_id=tenant_id, next_incident_number=2)
        .on_conflict_do_update(
            index_elements=["tenant_id"],
            set_={"next_incident_number": TenantCounter.next_incident_number + 1},
        )
        .returning(TenantCounter.next_incident_number)
    )
    allocated = await session.scalar(statement)
    # RETURNING gives the post-update value, so the number just handed out is
    # one less. On first insert that is 1.
    return int(allocated) - 1


async def _recent_resolved(
    session: AsyncSession, tenant_id: uuid.UUID, fingerprint_value: str, now: datetime
) -> Incident | None:
    """A case with this fingerprint closed in the last week.

    Reopening is never automatic. An alert after resolution creates a new
    incident linked to the old one, so the analyst sees "this recurred" rather
    than a closed case silently springing back open.
    """
    return await session.scalar(
        select(Incident)
        .where(
            Incident.tenant_id == tenant_id,
            Incident.fingerprint == fingerprint_value,
            Incident.status.in_(CLOSED_STATUSES),
            Incident.closed_at >= now - timedelta(days=RELATED_LOOKBACK_DAYS),
        )
        .order_by(Incident.closed_at.desc())
        .limit(1)
    )


async def attach_or_create(
    session: AsyncSession,
    *,
    alert: AlertFacts,
    grouping_window_minutes: int,
    policy: list[TenantSla],
) -> tuple[Incident, bool]:
    """Group one alert. Returns (incident, created). Does not commit.

    Note the interaction between two rules in DESIGN.md. §6 says an alert outside
    the grouping window starts a new incident, but the partial unique index on
    (tenant_id, fingerprint) where status is open forbids a second open case with
    the same fingerprint, and §6 also says to resolve that conflict by retrying
    the attach path. The index wins, so **while an incident is open the window has
    no effect**: a late alert joins the existing case rather than opening a
    parallel one. That is the coarse-grouping outcome the design asks for -
    fewer, fatter incidents - reached without a guaranteed conflict and retry on
    every late alert. The window becomes meaningful again only if stale incidents
    are ever auto-closed, which is deliberately not done: closing a case behind an
    analyst is worse than a fat one.
    """
    open_incident = await session.scalar(
        select(Incident).where(
            Incident.tenant_id == alert.tenant_id,
            Incident.fingerprint == alert.fingerprint,
            Incident.status.in_(OPEN_STATUSES),
        )
    )

    if open_incident is not None:
        late = alert.timestamp - open_incident.last_seen > timedelta(
            minutes=grouping_window_minutes
        )
        _attach(open_incident, alert, policy, late=late)
        return open_incident, False

    return await _create(session, alert, policy), True


def _attach(
    incident: Incident, alert: AlertFacts, policy: list[TenantSla], *, late: bool = False
) -> None:
    if late:
        # Recorded rather than acted on, so the queue can show "this case went
        # quiet and came back" without a second incident.
        summary = dict(incident.rule_summary or {})
        summary["_late_arrivals"] = int(summary.get("_late_arrivals", 0)) + 1
        incident.rule_summary = summary
    incident.last_seen = max(incident.last_seen, alert.timestamp)
    incident.first_seen = min(incident.first_seen, alert.timestamp)
    incident.alert_count = (incident.alert_count or 0) + 1

    summary = dict(incident.rule_summary or {})
    key = str(alert.rule_id)
    summary[key] = int(summary.get(key, 0)) + 1
    incident.rule_summary = summary

    if alert.rule_level > incident.severity:
        incident.severity = alert.rule_level
        # Rising severity re-tightens the clock, but only while unanswered, and
        # it recomputes against time already held awaiting the client.
        sla.apply_on_escalation(incident, sla.band_for(policy, incident.severity))

    incident.evidence = evidence.update(
        incident.evidence,
        ecs=alert.ecs,
        related=alert.related,
        timestamp=alert.timestamp,
        rule_desc=alert.rule_desc,
        rule_level=alert.rule_level,
        is_first=False,
    )
    incident.updated_at = datetime.now(UTC)


async def _create(session: AsyncSession, alert: AlertFacts, policy: list[TenantSla]) -> Incident:
    now = datetime.now(UTC)
    number = await next_incident_number(session, alert.tenant_id)

    incident = Incident(
        tenant_id=alert.tenant_id,
        number=number,
        title=alert.rule_desc[:MAX_TITLE],
        status="new",
        severity=alert.rule_level,
        fingerprint=alert.fingerprint,
        first_seen=alert.timestamp,
        last_seen=alert.timestamp,
        alert_count=1,
        rule_summary={str(alert.rule_id): 1},
        evidence=evidence.update(
            {},
            ecs=alert.ecs,
            related=alert.related,
            timestamp=alert.timestamp,
            rule_desc=alert.rule_desc,
            rule_level=alert.rule_level,
            is_first=True,
        ),
        created_at=now,
        updated_at=now,
    )
    sla.apply_on_create(incident, sla.band_for(policy, incident.severity))

    previous = await _recent_resolved(session, alert.tenant_id, alert.fingerprint, now)
    if previous is not None:
        incident.related_incident_id = previous.id

    session.add(incident)
    await session.flush()
    return incident
