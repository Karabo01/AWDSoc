"""The M6-M8 route surface: it exists, it is closed by default, and it did not
quietly reintroduce a caller-named tenant.

These are cheap assertions against the generated schema and against an anonymous
client. They cannot prove the handlers are correct - that needs a database - but
they do prove the two things most likely to regress silently: a route that
forgets its bearer dependency, and a route that accepts tenancy from the request.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

NEW_ROUTES = [
    ("GET", "/api/v1/entities"),
    ("GET", "/api/v1/entities/ip/1.2.3.4"),
    ("GET", "/api/v1/entities/ip/1.2.3.4/alerts"),
    ("GET", "/api/v1/entities/ip/1.2.3.4/incidents"),
    ("GET", "/api/v1/agents"),
    ("GET", "/api/v1/agents/000"),
    ("GET", "/api/v1/agents/000/alerts"),
    ("POST", "/api/v1/agents/sync"),
    ("GET", "/api/v1/rules/5712"),
    ("GET", "/api/v1/coverage/mitre"),
    ("GET", "/api/v1/overview"),
    ("GET", "/api/v1/users"),
    ("POST", "/api/v1/incidents/bulk"),
]


@pytest.mark.parametrize(("method", "path"), NEW_ROUTES)
def test_every_new_route_rejects_an_anonymous_caller(method, path):
    response = client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_the_new_routes_are_actually_registered():
    """Guards the test above: a 404 also produces a non-200, so without this a
    typo in a path would look like a passing auth check."""
    paths = app.openapi()["paths"]
    for expected in (
        "/api/v1/entities",
        "/api/v1/agents",
        "/api/v1/coverage/mitre",
        "/api/v1/overview",
        "/api/v1/users",
        "/api/v1/incidents/bulk",
        "/api/v1/incidents/stream",
    ):
        assert expected in paths, expected


def test_the_stream_route_is_matched_before_the_incident_id_route():
    """`/incidents/stream` must resolve as a literal.

    Starlette matches in registration order, and `{incident_id}` is a string
    pattern at the routing layer regardless of its UUID annotation - so if the
    detail route came first, the stream would 422 on "stream" not being a UUID.
    The OpenAPI path map preserves registration order, which is what is asserted.
    """
    paths = list(app.openapi()["paths"])
    assert paths.index("/api/v1/incidents/stream") < paths.index(
        "/api/v1/incidents/{incident_id}"
    )


def test_agent_sync_takes_no_tenant_parameter():
    """Naming a tenant here would be the caller choosing whose manager we connect
    to, which is exactly what tenancy-from-the-token prevents. The broad check in
    test_app.py covers this too; this one names the route so a regression points
    straight at it."""
    operation = app.openapi()["paths"]["/api/v1/agents/sync"]["post"]
    names = [p["name"] for p in operation.get("parameters", [])]
    assert not any("tenant" in name.lower() for name in names), names


def test_the_stream_takes_a_token_parameter_and_only_the_stream():
    """EventSource cannot set headers, so this one route reads its credential from
    the query string. Asserting it is the only one keeps that from spreading."""
    offenders = []
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            for param in operation.get("parameters", []):
                if param["name"] == "token" and param.get("in") == "query":
                    offenders.append(f"{method.upper()} {path}")

    # The `/v1` mount carries the same routes but is `include_in_schema=False`,
    # so only the documented prefix appears here.
    assert offenders == ["GET /api/v1/incidents/stream"], offenders
