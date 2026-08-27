"""End-to-end through the handler, with Redis and Postgres stubbed out.

The assertion that matters most here: a rejected request must not reach Redis at
all. If it did, an unauthenticated caller could consume another tenant's rate
budget or spend replay nonces.
"""

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.ingest import stream
from app.ingest.auth import CachedTenant, expected_signature, tenant_cache
from app.main import app

SECRET = "a-tenant-ingest-secret"
ALERT = {
    "id": "1756252800.123456",
    "timestamp": "2026-08-27T09:15:00.123+0000",
    "rule": {"level": 10, "id": "5710", "description": "SSH brute force"},
    "agent": {"id": "001", "name": "web01"},
}

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def published(monkeypatch):
    """Records what reached Redis. Empty means Redis was never touched."""
    calls = []

    async def fake_publish(*, tenant_id, signature, alerts):
        calls.append({"tenant_id": tenant_id, "signature": signature, "alerts": alerts})
        return len(alerts)

    monkeypatch.setattr(stream, "publish", fake_publish)
    return calls


@pytest.fixture(autouse=True)
def known_tenant(monkeypatch):
    tenant = CachedTenant(
        id=uuid.uuid4(), slug="acme-corp", secret=SECRET, status="active", cidrs=()
    )
    tenant_cache.invalidate()

    async def fake_load(slug):
        return tenant if slug == "acme-corp" else None

    monkeypatch.setattr(type(tenant_cache), "_load", staticmethod(fake_load))
    yield tenant
    tenant_cache.invalidate()


def post(body=None, *, slug="acme-corp", secret=SECRET, timestamp=None, signature=None):
    raw = json.dumps(body if body is not None else ALERT, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(time.time()))
    if signature is None:
        signature = "sha256=" + expected_signature(secret, timestamp, raw)
    return client.post(
        f"/api/v1/ingest/wazuh/{slug}",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-AWD-Timestamp": timestamp,
            "X-AWD-Signature": signature,
        },
    )


def test_a_valid_alert_is_accepted(published):
    response = post()
    assert response.status_code == 202
    assert response.json() == {"accepted": 1}
    assert len(published) == 1
    assert published[0]["alerts"][0]["id"] == ALERT["id"]


def test_an_array_of_alerts_is_accepted_from_day_one(published):
    """So a batching sidecar can arrive without an API change."""
    response = post([ALERT, {**ALERT, "id": "1756252800.2"}])
    assert response.status_code == 202
    assert response.json() == {"accepted": 2}
    assert len(published[0]["alerts"]) == 2


def test_the_tenant_comes_from_the_path_not_the_payload(published, known_tenant):
    post({**ALERT, "tenant_id": str(uuid.uuid4()), "tenant": "someone-else"})
    assert published[0]["tenant_id"] == str(known_tenant.id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slug": "not-a-client"},
        {"secret": "the-wrong-secret"},
        {"timestamp": str(int(time.time()) - 3600)},
        {"signature": "sha256=" + "0" * 64},
        {"signature": "not-even-prefixed"},
    ],
    ids=["unknown-slug", "bad-signature", "stale-timestamp", "forged", "malformed"],
)
def test_every_rejection_is_an_identical_401(published, kwargs):
    response = post(**kwargs)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorised."}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slug": "not-a-client"},
        {"secret": "the-wrong-secret"},
        {"timestamp": str(int(time.time()) - 3600)},
    ],
    ids=["unknown-slug", "bad-signature", "stale-timestamp"],
)
def test_a_rejected_request_never_reaches_redis(published, kwargs):
    post(**kwargs)
    assert published == [], "an unauthenticated caller must not touch Redis"


def test_a_rejection_reveals_nothing_about_which_check_failed(published):
    unknown = post(slug="not-a-client")
    bad_signature = post(secret="the-wrong-secret")
    assert unknown.json() == bad_signature.json()
    assert unknown.status_code == bad_signature.status_code


def test_a_replayed_body_is_rejected(published, monkeypatch):
    async def replayed(*, tenant_id, signature, alerts):
        return stream.Accepted.REPLAY

    monkeypatch.setattr(stream, "publish", replayed)
    response = post()
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorised."}


def test_rate_limiting_returns_429_with_a_retry_after(published, monkeypatch):
    async def limited(*, tenant_id, signature, alerts):
        return stream.Accepted.RATE_LIMITED

    monkeypatch.setattr(stream, "publish", limited)
    response = post()
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_the_signature_prefix_is_stripped_before_it_becomes_a_replay_key(published):
    post()
    assert not published[0]["signature"].startswith("sha256=")
    assert len(published[0]["signature"]) == 64


def test_a_body_that_is_not_json_is_a_400_not_a_401(published):
    raw = b"{not json"
    timestamp = str(int(time.time()))
    response = client.post(
        "/api/v1/ingest/wazuh/acme-corp",
        content=raw,
        headers={
            "X-AWD-Timestamp": timestamp,
            "X-AWD-Signature": "sha256=" + expected_signature(SECRET, timestamp, raw),
        },
    )
    assert response.status_code == 400
    assert published == []


def test_an_alert_that_is_not_an_object_is_refused(published):
    response = post(["not-an-object"])
    assert response.status_code == 400
    assert published == []


def test_an_oversized_batch_is_refused(published):
    from app.config import settings

    response = post([ALERT] * (settings.ingest_max_batch + 1))
    assert response.status_code == 413
    assert published == []


def test_an_empty_array_is_accepted_and_publishes_nothing(published):
    response = post([])
    assert response.status_code == 202
    assert response.json() == {"accepted": 0}
    assert published == []


def test_the_ingest_endpoint_needs_no_bearer_token(published):
    """It is HMAC-authenticated. A JWT dependency here would break every client
    manager on day one."""
    assert post().status_code == 202


def test_a_database_outage_returns_503_so_the_integrator_retries(
    published, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    async def explode(slug):
        raise OperationalError("select 1", {}, Exception("no postgres"))

    tenant_cache.invalidate()
    monkeypatch.setattr(type(tenant_cache), "_load", staticmethod(explode))
    response = post()
    assert response.status_code == 503
    assert response.headers["Retry-After"]
    assert published == []
