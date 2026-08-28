"""Reports leave the console for an audience that cannot see it.

Everything here guards that boundary. The builder's queries need a database and
are not exercised, but the parts that decide *what a client is allowed to see*
are pure or schema-level, and those are the ones worth pinning.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Incident, TenantSla
from app.reports import builder
from app.schemas.report import ReportCreate

client = TestClient(app, raise_server_exceptions=False)


def incident(**kwargs) -> Incident:
    base = dict(
        first_seen=datetime(2026, 8, 1, tzinfo=UTC),
        sla_respond_by=datetime(2026, 8, 1, 4, tzinfo=UTC),
        sla_resolve_by=datetime(2026, 8, 2, tzinfo=UTC),
        sla_paused_at=None,
        sla_paused_seconds=0,
        first_response_at=None,
        closed_at=None,
        severity=10,
        status="new",
    )
    base.update(kwargs)
    return Incident(**base)


def band(severity_min=7, respond=240, resolve=1440) -> TenantSla:
    return TenantSla(
        severity_min=severity_min, respond_minutes=respond, resolve_minutes=resolve
    )


NOW = datetime(2026, 8, 10, tzinfo=UTC)


# --- the SLA section --------------------------------------------------------


def test_a_tenant_with_no_policy_reports_no_sla_rather_than_a_perfect_one():
    """Zero breaches against a contract that does not exist reads to a paying
    client as perfect performance. It has to say "not configured" instead."""
    section = builder._sla_section([], [incident()], NOW)
    assert section == {"configured": False}
    assert "response_breached" not in section


def test_a_met_response_is_not_counted_as_a_breach():
    answered = incident(first_response_at=datetime(2026, 8, 1, 1, tzinfo=UTC))
    section = builder._sla_section([band()], [answered], NOW)
    assert section["response_breached"] == 0
    assert section["responded"] == 1
    assert section["response_met_pct"] == 100.0


def test_a_late_response_is_counted_as_a_breach():
    late = incident(first_response_at=datetime(2026, 8, 1, 9, tzinfo=UTC))
    section = builder._sla_section([band()], [late], NOW)
    assert section["response_breached"] == 1
    assert section["response_met_pct"] == 0.0


def test_an_unanswered_case_past_its_deadline_is_a_breach():
    """Derived against `now`, exactly as the queue derives it - not stored."""
    section = builder._sla_section([band()], [incident()], NOW)
    assert section["response_breached"] == 1
    assert section["responded"] == 0


def test_a_paused_case_inside_its_deadline_has_not_breached():
    """The clock stops in `pending`. A client cannot be billed a breach for time
    they were the ones holding."""
    paused = incident(sla_paused_at=datetime(2026, 8, 1, 2, tzinfo=UTC))
    section = builder._sla_section([band()], [paused], NOW)
    assert section["response_breached"] == 0


def test_time_awaiting_the_client_is_reported():
    """It belongs in the report because it is the answer to "why did this take
    four days" - and the client is the one who was asked."""
    held = incident(
        first_response_at=datetime(2026, 8, 1, 1, tzinfo=UTC), sla_paused_seconds=7200
    )
    section = builder._sla_section([band()], [held], NOW)
    assert section["awaiting_client_hours"] == 2.0


def test_cases_with_no_deadline_are_not_measured():
    """A case opened below every band has no SLA. Counting it as met would
    inflate the percentage with cases nobody promised anything about."""
    unmeasured = incident(sla_respond_by=None, sla_resolve_by=None)
    section = builder._sla_section([band()], [unmeasured], NOW)
    assert section["measured"] == 0
    assert section["response_met_pct"] is None


def test_the_median_response_is_reported_not_the_mean():
    """One case that sat over a weekend should not move the headline number."""
    incidents = [
        incident(first_response_at=datetime(2026, 8, 1, 0, 10, tzinfo=UTC)),
        incident(first_response_at=datetime(2026, 8, 1, 0, 20, tzinfo=UTC)),
        incident(first_response_at=datetime(2026, 8, 3, tzinfo=UTC)),
    ]
    section = builder._sla_section([band()], incidents, NOW)
    assert section["median_response_minutes"] == 20.0


# --- the period -------------------------------------------------------------


def test_a_backwards_period_is_refused():
    with pytest.raises(ValidationError):
        ReportCreate(
            period_start=datetime(2026, 9, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 1, tzinfo=UTC),
        )


def test_an_empty_period_is_refused():
    same = datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        ReportCreate(period_start=same, period_end=same)


def test_an_absurd_period_is_refused():
    with pytest.raises(ValidationError):
        ReportCreate(
            period_start=datetime(2020, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_a_normal_month_is_accepted():
    payload = ReportCreate(
        period_start=datetime(2026, 8, 1, tzinfo=UTC),
        period_end=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert (payload.period_end - payload.period_start) == timedelta(days=31)


# --- the API surface --------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/reports"),
        ("POST", "/api/v1/reports"),
        ("POST", "/api/v1/reports/preview"),
        ("GET", "/api/v1/reports/00000000-0000-0000-0000-000000000000"),
        ("PATCH", "/api/v1/reports/00000000-0000-0000-0000-000000000000"),
        ("POST", "/api/v1/reports/00000000-0000-0000-0000-000000000000/issue"),
        ("DELETE", "/api/v1/reports/00000000-0000-0000-0000-000000000000"),
    ],
)
def test_every_report_route_rejects_an_anonymous_caller(method, path):
    response = client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_the_report_routes_are_registered():
    """Guards the test above - a 404 is also not a 200."""
    paths = app.openapi()["paths"]
    for expected in (
        "/api/v1/reports",
        "/api/v1/reports/preview",
        "/api/v1/reports/{report_id}",
        "/api/v1/reports/{report_id}/issue",
    ):
        assert expected in paths, expected


def test_reports_take_no_tenant_parameter():
    """A report covers one client, and which client comes from the token. Naming
    one here would let a caller generate against a tenant they cannot read."""
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/reports"):
            continue
        for operation in operations.values():
            names = [p["name"] for p in operation.get("parameters", [])]
            assert not any("tenant" in n.lower() for n in names), (path, names)


def test_the_builder_only_counts_client_visible_comments():
    """Internal commentary must never reach a client document. The filter is in
    the query, so this asserts the source rather than a runtime result."""
    import inspect

    source = inspect.getsource(builder.build)
    assert 'IncidentComment.visibility == "client"' in source


def test_the_builder_cannot_be_called_without_naming_one_tenant():
    """A cross-tenant report is a cross-client leak into a document we email out.

    Rather than counting queries, this pins the shape that makes the leak
    impossible to write by accident: the entry point takes a `Tenant`, and every
    helper that touches alert data takes a `tenant_id`. A new query inside them
    has a tenant in scope and nothing to filter by if it does not use it.
    """
    import inspect

    signature = inspect.signature(builder.build)
    assert "tenant" in signature.parameters
    assert signature.parameters["tenant"].default is inspect.Parameter.empty

    figures = inspect.signature(builder._alert_figures)
    assert "tenant_id" in figures.parameters
    assert figures.parameters["tenant_id"].default is inspect.Parameter.empty


def test_the_builder_takes_no_list_of_tenants():
    """Guards the test above: a `tenant_ids` parameter would satisfy it while
    reintroducing exactly the fan-out it exists to prevent."""
    import inspect

    for name, function in vars(builder).items():
        if not callable(function) or not name.startswith(("build", "_")):
            continue
        try:
            parameters = inspect.signature(function).parameters
        except (TypeError, ValueError):
            continue
        assert "tenant_ids" not in parameters, name
