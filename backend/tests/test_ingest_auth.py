"""The trust boundary.

DESIGN.md §13: unknown slug, wrong signature, stale timestamp, replayed body and
disallowed IP must all return 401 without touching Redis, in comparable time.
"""

import time
import uuid

import pytest

from app.config import settings
from app.ingest.auth import (
    CachedTenant,
    Rejection,
    authenticate,
    client_ip,
    expected_signature,
    ip_is_allowed,
    tenant_cache,
    timestamp_is_fresh,
)

SECRET = "a-tenant-ingest-secret"
BODY = b'{"rule":{"level":10,"id":"5710"},"id":"1724668800.1"}'


@pytest.fixture(autouse=True)
def known_tenant(monkeypatch):
    """Seed the cache so nothing here needs a database."""
    tenant = CachedTenant(
        id=uuid.uuid4(),
        slug="acme-corp",
        secret=SECRET,
        status="active",
        cidrs=("41.1.2.0/24",),
    )
    tenant_cache.invalidate()

    async def fake_load(slug):
        return tenant if slug == "acme-corp" else None

    monkeypatch.setattr(type(tenant_cache), "_load", staticmethod(fake_load))
    yield tenant
    tenant_cache.invalidate()


def signed(secret=SECRET, body=BODY, timestamp=None):
    timestamp = timestamp or str(int(time.time()))
    return timestamp, "sha256=" + expected_signature(secret, timestamp, body)


async def call(**overrides):
    timestamp, signature = signed()
    kwargs = {
        "slug": "acme-corp",
        "body": BODY,
        "signature_header": signature,
        "timestamp_header": timestamp,
        "source_ip": "41.1.2.9",
    }
    kwargs.update(overrides)
    return await authenticate(**kwargs)


async def test_a_correctly_signed_alert_from_an_allowed_address_is_accepted():
    result = await call()
    assert result.ok
    assert result.tenant.slug == "acme-corp"


async def test_an_unknown_slug_is_rejected():
    result = await call(slug="not-a-client")
    assert not result.ok
    assert result.reason is Rejection.UNKNOWN_TENANT


async def test_a_wrong_signature_is_rejected():
    timestamp, signature = signed(secret="the-wrong-secret")
    result = await call(signature_header=signature, timestamp_header=timestamp)
    assert not result.ok
    assert result.reason is Rejection.BAD_SIGNATURE


async def test_a_tampered_body_is_rejected():
    timestamp, signature = signed()
    result = await call(
        body=BODY.replace(b'"level":10', b'"level":3'),
        signature_header=signature,
        timestamp_header=timestamp,
    )
    assert not result.ok
    assert result.reason is Rejection.BAD_SIGNATURE


async def test_a_signature_without_the_sha256_prefix_is_rejected():
    timestamp = str(int(time.time()))
    result = await call(
        signature_header=expected_signature(SECRET, timestamp, BODY),
        timestamp_header=timestamp,
    )
    assert not result.ok
    assert result.reason is Rejection.MALFORMED_SIGNATURE


async def test_a_missing_signature_is_rejected():
    result = await call(signature_header=None)
    assert not result.ok


async def test_a_stale_timestamp_is_rejected():
    old = str(int(time.time()) - settings.ingest_max_skew_seconds - 60)
    timestamp, signature = signed(timestamp=old)
    result = await call(signature_header=signature, timestamp_header=timestamp)
    assert not result.ok
    assert result.reason is Rejection.STALE_TIMESTAMP


async def test_a_timestamp_far_in_the_future_is_rejected():
    ahead = str(int(time.time()) + settings.ingest_max_skew_seconds + 60)
    timestamp, signature = signed(timestamp=ahead)
    result = await call(signature_header=signature, timestamp_header=timestamp)
    assert not result.ok
    assert result.reason is Rejection.STALE_TIMESTAMP


async def test_a_signature_from_another_timestamp_cannot_be_reused():
    """The timestamp is inside the signed material, so lifting a signature onto
    a fresh header fails."""
    old = str(int(time.time()) - 30)
    _, signature = signed(timestamp=old)
    result = await call(
        signature_header=signature, timestamp_header=str(int(time.time()))
    )
    assert not result.ok
    assert result.reason is Rejection.BAD_SIGNATURE


async def test_an_address_outside_the_allowlist_is_rejected():
    result = await call(source_ip="197.5.5.5")
    assert not result.ok
    assert result.reason is Rejection.DISALLOWED_IP


async def test_a_suspended_tenant_is_rejected():
    tenant_cache._entries["acme-corp"] = (
        CachedTenant(
            id=uuid.uuid4(),
            slug="acme-corp",
            secret=SECRET,
            status="suspended",
            cidrs=(),
        ),
        time.monotonic(),
    )
    result = await call()
    assert not result.ok
    assert result.reason is Rejection.TENANT_INACTIVE


async def test_a_database_outage_asks_for_a_retry_rather_than_rejecting(monkeypatch):
    """A 401 makes the integrator give up and lose the alert; a 503 makes it
    retry. With nothing cached we cannot decide, so we must ask for a retry."""
    from sqlalchemy.exc import OperationalError

    async def explode(slug):
        raise OperationalError("select 1", {}, Exception("no postgres"))

    tenant_cache.invalidate()
    monkeypatch.setattr(type(tenant_cache), "_load", staticmethod(explode))
    result = await call()
    assert not result.ok
    assert result.reason is Rejection.LOOKUP_UNAVAILABLE


async def test_a_cached_tenant_survives_a_database_outage(monkeypatch, known_tenant):
    """Ingestion must keep buffering when Postgres is degraded."""
    from sqlalchemy.exc import OperationalError

    assert (await call()).ok  # warm the cache

    async def explode(slug):
        raise OperationalError("select 1", {}, Exception("no postgres"))

    monkeypatch.setattr(type(tenant_cache), "_load", staticmethod(explode))
    monkeypatch.setattr(settings, "tenant_cache_soft_ttl", 0)  # force a refresh
    result = await call()
    assert result.ok, "a stale cached tenant must still authenticate"


# --- the individual predicates ------------------------------------------------


def test_an_empty_allowlist_permits_any_source():
    assert ip_is_allowed("8.8.8.8", ())


def test_an_allowlist_with_no_source_address_denies():
    assert not ip_is_allowed(None, ("41.1.2.0/24",))


def test_ipv6_allowlisting_works():
    assert ip_is_allowed("2001:db8::5", ("2001:db8::/32",))
    assert not ip_is_allowed("2001:dba::5", ("2001:db8::/32",))


def test_an_unparseable_cidr_does_not_crash_the_check():
    assert not ip_is_allowed("41.1.2.9", ("not-a-cidr",))


def test_a_non_numeric_timestamp_is_not_fresh():
    assert not timestamp_is_fresh("yesterday")
    assert not timestamp_is_fresh("")


def test_the_forwarded_header_is_read_from_the_right():
    """Traefik appends the real peer. Reading the leftmost entry would let a
    client spoof its own source address and walk straight through the
    allowlist."""
    assert client_ip("1.2.3.4, 41.1.2.9", "10.0.0.1") == "41.1.2.9"


def test_a_spoofed_forwarded_header_cannot_beat_the_allowlist():
    spoofed = client_ip("41.1.2.9", "197.5.5.5")
    # One trusted hop: the only entry is what Traefik observed.
    assert spoofed == "41.1.2.9"
    # And with the header absent we fall back to the socket peer.
    assert client_ip(None, "197.5.5.5") == "197.5.5.5"


def test_the_signature_matches_the_integrator_byte_for_byte():
    """The other half of this contract lives in deploy/wazuh/custom-awd-console.
    A mismatch here is silent data loss across the trust boundary."""
    import importlib.machinery
    import importlib.util
    import pathlib

    script = (
        pathlib.Path(__file__).resolve().parents[2]
        / "deploy"
        / "wazuh"
        / "custom-awd-console"
    )
    loader = importlib.machinery.SourceFileLoader("integrator_contract", str(script))
    spec = importlib.util.spec_from_loader("integrator_contract", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    timestamp = "1756252800"
    body = '{"rule":{"level":10}}'
    assert module.sign(SECRET, timestamp, body) == expected_signature(
        SECRET, timestamp, body.encode()
    )


async def test_every_path_performs_exactly_one_hmac(monkeypatch):
    """Uniform failure, asserted structurally rather than by wall clock.

    Timing tests are flaky; the invariant that actually matters is that the
    unknown-tenant path does the same cryptographic work as the known one, so
    response time cannot be used to enumerate tenants.
    """
    import app.ingest.auth as auth_module

    # Build the signed request BEFORE patching, or the test's own HMAC is counted.
    timestamp, signature = signed()

    counts = []
    real_new = auth_module.hmac.new

    def counting_new(*args, **kwargs):
        counts.append(1)
        return real_new(*args, **kwargs)

    monkeypatch.setattr(auth_module.hmac, "new", counting_new)

    for slug in ("acme-corp", "not-a-client"):
        counts.clear()
        await authenticate(
            slug=slug,
            body=BODY,
            signature_header=signature,
            timestamp_header=timestamp,
            source_ip="41.1.2.9",
        )
        assert sum(counts) == 1, f"{slug} did {sum(counts)} HMACs"


async def test_the_dummy_secret_is_never_a_working_key():
    """The unknown-tenant path signs against a placeholder. If that placeholder
    ever validated a request, unknown slugs would authenticate."""
    from app.ingest.auth import _DUMMY_SECRET

    timestamp, signature = signed(secret=_DUMMY_SECRET)
    result = await call(
        slug="not-a-client", signature_header=signature, timestamp_header=timestamp
    )
    assert not result.ok
