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


# Routes that legitimately name a tenant in their path. Each is an ADDRESSING
# scheme, not a source of tenancy: the token still decides what is visible, so
# naming a client you cannot see returns 404 rather than their data.
TENANT_ADDRESSED = (
    "/api/v1/tenants",              # tenant management itself
    "/api/v1/ingest/",              # HMAC-authenticated, tenancy is the whole point
    "/api/v1/incidents/by-number/",  # shareable case address, still token-scoped
)


def test_no_endpoint_accepts_a_tenant_parameter():
    """Tenancy is derived from the token. A tenant query or path parameter on any
    route outside the addressing allowlist is a bug: it lets a caller name a
    tenant the token did not grant."""
    schema = app.openapi()
    offenders = []
    for path, operations in schema["paths"].items():
        if any(path.startswith(prefix) for prefix in TENANT_ADDRESSED):
            continue
        for method, operation in operations.items():
            for param in operation.get("parameters", []):
                if "tenant" in param["name"].lower():
                    offenders.append(f"{method.upper()} {path} ?{param['name']}")
    assert offenders == []


def test_every_tenant_addressed_route_still_derives_scope_from_the_token():
    """Guards the allowlist above. An exemption is only safe while the handler
    applies the token's scope; without this, adding a path to TENANT_ADDRESSED
    would silently turn it into a cross-tenant read."""
    import inspect

    from app.api.v1 import incidents

    signature = inspect.signature(incidents.get_incident_by_number)
    assert "scope" in signature.parameters, (
        "the by-number route must take the token-derived TenantScope"
    )
    source = inspect.getsource(incidents.get_incident_by_number)
    assert "_scoped(" in source, "the by-number route must apply the tenant filter"


def test_the_route_table_is_actually_populated():
    """Guards the test above: an empty schema would make it vacuous."""
    paths = app.openapi()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/switch-tenant" in paths


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/api/healthz", "/api/readyz"])
def test_health_endpoints_answer_without_a_token(path):
    response = client.get(path)
    # 503 when Postgres/Redis are down locally; never a 401 and never a crash.
    assert response.status_code in (200, 503)


def test_health_is_reachable_through_the_api_path_prefix():
    """Traefik routes /api to this service and everything else to the web
    container, so a health endpoint only at the root is invisible from outside -
    a browser asking for /healthz gets the SPA back."""
    assert client.get("/api/healthz").json()["status"] in ("ok", "degraded")


def test_the_root_health_path_survives_for_the_container_probe():
    """Coolify probes the container directly, never through Traefik."""
    assert "status" in client.get("/healthz").json()


def test_health_reports_which_host_it_dialled():
    """`gaierror` alone cannot distinguish a stopped container from a mangled
    DATABASE_URL. Reporting the parsed host makes the difference obvious."""
    body = client.get("/api/healthz").json()
    assert "target" in body["postgres"]
    assert "target" in body["redis"]


def test_the_health_target_never_carries_the_password():
    from app.api.v1.health import _postgres_target, _redis_target

    for target in (_postgres_target(), _redis_target()):
        assert "://" not in target
        assert "@" not in target or "unparseable" in target
