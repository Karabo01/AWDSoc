import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_protected_routes_reject_an_anonymous_caller():
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_a_forged_bearer_token_is_rejected():
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


def test_switch_tenant_is_not_reachable_without_a_token():
    response = client.post("/api/v1/auth/switch-tenant", json={"tenant_id": None})
    assert response.status_code == 401


def test_no_endpoint_accepts_a_tenant_parameter():
    """Tenancy is derived from the token. A tenant query or path parameter on any
    route other than the tenant-management endpoints themselves is a bug: it lets
    a caller name a tenant the token did not grant."""
    schema = app.openapi()
    offenders = []
    for path, operations in schema["paths"].items():
        if path.startswith("/api/v1/tenants") or "/ingest/" in path:
            continue  # addressed by id or slug by design
        for method, operation in operations.items():
            for param in operation.get("parameters", []):
                if "tenant" in param["name"].lower():
                    offenders.append(f"{method.upper()} {path} ?{param['name']}")
    assert offenders == []


def test_the_route_table_is_actually_populated():
    """Guards the test above: an empty schema would make it vacuous."""
    paths = app.openapi()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/switch-tenant" in paths


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_health_endpoints_answer_without_a_token(path):
    response = client.get(path)
    # 503 when Postgres/Redis are down locally; never a 401 and never a crash.
    assert response.status_code in (200, 503)
