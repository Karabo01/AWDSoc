"""The SLA clock.

Five rules, per DESIGN.md §4, because the ambiguous cases are where this gets
argued with a client later:

1. It starts at `first_seen`, not at incident creation.
2. `first_response_at` is stamped once, by whichever comes first: a status change
   out of `new`, an assignment, or a comment.
3. **The clock stops in `pending`**, which means *awaiting client feedback*.
   Rather than accumulate elapsed time, the deadlines are pushed forward on
   resume, so they stay absolute timestamps the queue can order by.
4. Rising severity re-tightens the clock, but only until it is answered - and it
   recomputes against `sla_paused_seconds`, so it cannot claw back time the
   client already held.
5. Every pause is auditable, because a paused clock cannot breach.

Breach is derived, never stored. A stored flag needs a worker sweep that can lag,
and a lagging breach flag is worse than none.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, TenantSla

PAUSED_STATUS = "pending"
CLOSED_STATUSES = ("resolved", "false_positive")


@dataclass(frozen=True)
class SlaBand:
    respond_minutes: int
    resolve_minutes: int


async def policy_for(session: AsyncSession, tenant_id: uuid.UUID) -> list[TenantSla]:
    return list(
        await session.scalars(
            select(TenantSla)
            .where(TenantSla.tenant_id == tenant_id)
            .order_by(TenantSla.severity_min)
        )
    )


def band_for(policy: list[TenantSla], severity: int) -> SlaBand | None:
    """The row with the highest `severity_min` not exceeding this severity.

    No matching band means no SLA: the deadline columns stay null and the queue
    shows no countdown.
    """
    match = None
    for row in policy:
        if row.severity_min <= severity:
            match = row
        else:
            break
    if match is None:
        return None
    return SlaBand(respond_minutes=match.respond_minutes, resolve_minutes=match.resolve_minutes)


def deadlines(
    first_seen: datetime, band: SlaBand | None, *, paused_seconds: int = 0
) -> tuple[datetime | None, datetime | None]:
    """Absolute deadlines, offset by time already held awaiting the client."""
    if band is None:
        return None, None
    held = timedelta(seconds=paused_seconds)
    return (
        first_seen + timedelta(minutes=band.respond_minutes) + held,
        first_seen + timedelta(minutes=band.resolve_minutes) + held,
    )


def apply_on_create(incident: Incident, band: SlaBand | None) -> None:
    incident.sla_respond_by, incident.sla_resolve_by = deadlines(incident.first_seen, band)


def apply_on_escalation(incident: Incident, band: SlaBand | None) -> None:
    """Recompute after a severity increase, but only while unanswered.

    Once `first_response_at` is set both deadlines freeze: a case that was
    answered inside its SLA does not retroactively breach because a later alert
    raised its severity.
    """
    if incident.first_response_at is not None or band is None:
        return
    incident.sla_respond_by, incident.sla_resolve_by = deadlines(
        incident.first_seen, band, paused_seconds=incident.sla_paused_seconds or 0
    )


def mark_first_response(incident: Incident, *, now: datetime | None = None) -> bool:
    """Stamp the first real response. Returns True if this was the first.

    Opening a case is not a response; doing something to it is.
    """
    if incident.first_response_at is not None:
        return False
    incident.first_response_at = now or datetime.now(UTC)
    return True


def pause(incident: Incident, *, now: datetime | None = None) -> None:
    if incident.sla_paused_at is None:
        incident.sla_paused_at = now or datetime.now(UTC)


def resume(incident: Incident, *, now: datetime | None = None) -> int:
    """Push both deadlines forward by however long we were blocked. Returns the
    seconds held, which is the number that ends up in a client conversation."""
    if incident.sla_paused_at is None:
        return 0
    now = now or datetime.now(UTC)
    held = max(int((now - incident.sla_paused_at).total_seconds()), 0)
    if incident.sla_respond_by is not None:
        incident.sla_respond_by += timedelta(seconds=held)
    if incident.sla_resolve_by is not None:
        incident.sla_resolve_by += timedelta(seconds=held)
    incident.sla_paused_seconds = (incident.sla_paused_seconds or 0) + held
    incident.sla_paused_at = None
    return held


def apply_status_transition(
    incident: Incident, new_status: str, *, now: datetime | None = None
) -> dict:
    """Everything the clock has to do when status changes. Returns audit detail."""
    now = now or datetime.now(UTC)
    old_status = incident.status
    detail: dict = {"from": old_status, "to": new_status}

    if old_status == PAUSED_STATUS and new_status != PAUSED_STATUS:
        detail["held_seconds"] = resume(incident, now=now)
    elif new_status == PAUSED_STATUS and old_status != PAUSED_STATUS:
        pause(incident, now=now)
        detail["paused"] = True

    if new_status in CLOSED_STATUSES:
        incident.closed_at = now
        # A case closed while paused stops holding time against the client.
        if incident.sla_paused_at is not None:
            detail["held_seconds"] = resume(incident, now=now)
    elif old_status in CLOSED_STATUSES:
        incident.closed_at = None

    if new_status != "new" and mark_first_response(incident, now=now):
        detail["first_response"] = True

    incident.status = new_status
    incident.updated_at = now
    return detail


def response_breached(incident: Incident, *, now: datetime | None = None) -> bool:
    if incident.sla_respond_by is None:
        return False
    if incident.first_response_at is not None:
        return incident.first_response_at > incident.sla_respond_by
    if incident.sla_paused_at is not None:
        # Both frozen. A pause cannot un-breach something already breached.
        return incident.sla_paused_at > incident.sla_respond_by
    return (now or datetime.now(UTC)) > incident.sla_respond_by


def resolution_breached(incident: Incident, *, now: datetime | None = None) -> bool:
    if incident.sla_resolve_by is None:
        return False
    if incident.closed_at is not None:
        return incident.closed_at > incident.sla_resolve_by
    if incident.sla_paused_at is not None:
        return incident.sla_paused_at > incident.sla_resolve_by
    return (now or datetime.now(UTC)) > incident.sla_resolve_by
