"""The SLA clock.

Every rule here ends up in a conversation with a client about whether a breach
was real, so the ambiguous cases are the ones worth pinning down.
"""

from datetime import UTC, datetime, timedelta

from app.incidents import sla
from app.models import Incident, TenantSla

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def policy(*bands: tuple[int, int, int]) -> list[TenantSla]:
    return [
        TenantSla(severity_min=s, respond_minutes=r, resolve_minutes=x)
        for s, r, x in bands
    ]


def incident(**kw) -> Incident:
    base = dict(
        status="new",
        severity=10,
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
        sla_paused_seconds=0,
    )
    base.update(kw)
    return Incident(**base)


DEFAULT = policy((0, 480, 2880), (7, 60, 480), (10, 30, 240), (13, 15, 120))


# --- band selection -----------------------------------------------------------


def test_the_highest_band_not_exceeding_the_severity_wins():
    assert sla.band_for(DEFAULT, 12).respond_minutes == 30
    assert sla.band_for(DEFAULT, 13).respond_minutes == 15
    assert sla.band_for(DEFAULT, 7).respond_minutes == 60
    assert sla.band_for(DEFAULT, 3).respond_minutes == 480


def test_a_tenant_with_no_policy_has_no_sla():
    case = incident()
    sla.apply_on_create(case, sla.band_for([], case.severity))
    assert case.sla_respond_by is None
    assert case.sla_resolve_by is None


def test_no_band_below_the_lowest_floor_means_no_clock():
    assert sla.band_for(policy((10, 30, 240)), 7) is None


# --- the clock starts ---------------------------------------------------------


def test_the_clock_starts_at_first_seen_not_at_creation():
    """The client's exposure began when the alert fired."""
    case = incident(first_seen=NOW - timedelta(hours=2))
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    assert case.sla_respond_by == NOW - timedelta(hours=2) + timedelta(minutes=30)


# --- first response -----------------------------------------------------------


def test_first_response_is_stamped_once_and_never_moved():
    case = incident()
    assert sla.mark_first_response(case, now=NOW) is True
    assert sla.mark_first_response(case, now=NOW + timedelta(hours=1)) is False
    assert case.first_response_at == NOW


def test_leaving_new_counts_as_a_response():
    case = incident()
    sla.apply_status_transition(case, "active", now=NOW)
    assert case.first_response_at == NOW


def test_staying_in_new_is_not_a_response():
    """Opening a case is not a response; doing something to it is."""
    case = incident()
    assert case.first_response_at is None


# --- pausing ------------------------------------------------------------------


def test_entering_pending_stops_the_clock():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.apply_status_transition(case, "pending", now=NOW)
    assert case.sla_paused_at == NOW


def test_resuming_pushes_both_deadlines_forward_by_the_time_held():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    respond_before, resolve_before = case.sla_respond_by, case.sla_resolve_by

    sla.apply_status_transition(case, "pending", now=NOW)
    sla.apply_status_transition(case, "active", now=NOW + timedelta(hours=3))

    assert case.sla_respond_by == respond_before + timedelta(hours=3)
    assert case.sla_resolve_by == resolve_before + timedelta(hours=3)
    assert case.sla_paused_at is None
    assert case.sla_paused_seconds == 3 * 3600


def test_time_held_accumulates_across_several_pauses():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    at = NOW
    for _ in range(3):
        sla.apply_status_transition(case, "pending", now=at)
        at += timedelta(hours=1)
        sla.apply_status_transition(case, "active", now=at)
        at += timedelta(minutes=10)
    assert case.sla_paused_seconds == 3 * 3600


def test_a_paused_clock_cannot_breach():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.apply_status_transition(case, "pending", now=NOW)
    # Days later, still paused, still not breached.
    assert not sla.response_breached(case, now=NOW + timedelta(days=5))


def test_a_pause_cannot_un_breach_something_already_breached():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    case.first_response_at = None
    late = NOW + timedelta(hours=4)
    sla.apply_status_transition(case, "pending", now=late)
    assert sla.response_breached(case, now=late + timedelta(days=1))


def test_closing_while_paused_stops_holding_time_against_the_client():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.apply_status_transition(case, "pending", now=NOW)
    sla.apply_status_transition(case, "resolved", now=NOW + timedelta(hours=2))
    assert case.sla_paused_at is None
    assert case.sla_paused_seconds == 2 * 3600
    assert case.closed_at == NOW + timedelta(hours=2)


# --- escalation ---------------------------------------------------------------


def test_rising_severity_re_tightens_an_unanswered_clock():
    case = incident(severity=7)
    sla.apply_on_create(case, sla.band_for(DEFAULT, 7))
    assert case.sla_respond_by == NOW + timedelta(minutes=60)

    case.severity = 13
    sla.apply_on_escalation(case, sla.band_for(DEFAULT, 13))
    assert case.sla_respond_by == NOW + timedelta(minutes=15)


def test_escalation_does_not_move_an_answered_clock():
    """A case answered inside its SLA does not retroactively breach because a
    later alert raised its severity."""
    case = incident(severity=7)
    sla.apply_on_create(case, sla.band_for(DEFAULT, 7))
    original = case.sla_respond_by
    sla.mark_first_response(case, now=NOW + timedelta(minutes=5))

    case.severity = 13
    sla.apply_on_escalation(case, sla.band_for(DEFAULT, 13))
    assert case.sla_respond_by == original


def test_escalation_cannot_claw_back_time_the_client_already_held():
    """This is what `sla_paused_seconds` is for. Without it, re-tightening after
    a pause would erase the hold."""
    case = incident(severity=7)
    sla.apply_on_create(case, sla.band_for(DEFAULT, 7))
    sla.apply_status_transition(case, "pending", now=NOW)
    sla.apply_status_transition(case, "new", now=NOW + timedelta(hours=2))
    case.first_response_at = None  # still unanswered

    case.severity = 13
    sla.apply_on_escalation(case, sla.band_for(DEFAULT, 13))
    assert case.sla_respond_by == NOW + timedelta(minutes=15) + timedelta(hours=2)


# --- breach derivation --------------------------------------------------------


def test_response_breach_when_the_deadline_passes_unanswered():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    assert not sla.response_breached(case, now=NOW + timedelta(minutes=29))
    assert sla.response_breached(case, now=NOW + timedelta(minutes=31))


def test_an_answer_inside_the_window_never_breaches_afterwards():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.mark_first_response(case, now=NOW + timedelta(minutes=10))
    assert not sla.response_breached(case, now=NOW + timedelta(days=30))


def test_a_late_answer_breaches_permanently():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.mark_first_response(case, now=NOW + timedelta(hours=5))
    assert sla.response_breached(case, now=NOW + timedelta(days=30))


def test_resolution_breach_uses_the_close_time_once_closed():
    case = incident()
    sla.apply_on_create(case, sla.band_for(DEFAULT, 10))
    sla.apply_status_transition(case, "resolved", now=NOW + timedelta(hours=1))
    assert not sla.resolution_breached(case, now=NOW + timedelta(days=10))


def test_a_tenant_without_an_sla_never_breaches():
    case = incident()
    sla.apply_on_create(case, sla.band_for([], case.severity))
    assert not sla.response_breached(case, now=NOW + timedelta(days=99))
    assert not sla.resolution_breached(case, now=NOW + timedelta(days=99))
