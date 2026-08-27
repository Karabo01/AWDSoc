"""The producer's wiring.

The Lua script itself needs a real Redis, which arrives on the VPS. What is
testable here - and where the bugs actually live - is the argument order handed
to it: KEYS and ARGV are positional, so an off-by-one silently rate-limits the
wrong key or drops alerts.
"""

import json
import uuid

import pytest

from app.config import settings
from app.ingest import stream


class FakeScript:
    def __init__(self):
        self.calls = []

    async def __call__(self, keys, args):
        self.calls.append({"keys": keys, "args": args})
        # Mimic the script's success return: the number of alerts queued.
        return int(args[5])


class FakeRedis:
    def __init__(self, script):
        self._script = script

    def register_script(self, source):
        self._script.source = source
        return self._script


@pytest.fixture
def script(monkeypatch):
    fake = FakeScript()
    monkeypatch.setattr(stream, "_script", None)
    monkeypatch.setattr(stream, "get_redis", lambda: FakeRedis(fake))
    return fake


async def test_publish_returns_the_number_queued(script):
    queued = await stream.publish(
        tenant_id="t1", signature="sig", alerts=[{"a": 1}, {"a": 2}]
    )
    assert queued == 2


async def test_the_three_keys_are_replay_rate_and_stream(script):
    await stream.publish(tenant_id="t1", signature="deadbeef", alerts=[{"a": 1}])
    keys = script.calls[0]["keys"]
    assert keys[0] == stream.replay_key("t1", "deadbeef")
    assert keys[1] == stream.rate_key("t1")
    assert keys[2] == settings.ingest_stream_key


async def test_the_replay_key_is_scoped_per_tenant():
    """Two tenants can legitimately produce the same signature only by using the
    same secret, but scoping costs nothing and removes the question."""
    assert stream.replay_key("a", "sig") != stream.replay_key("b", "sig")


async def test_the_rate_key_is_scoped_per_tenant():
    """One client's alert storm must not starve another's."""
    assert stream.rate_key("a") != stream.rate_key("b")


async def test_the_argument_order_matches_the_script(script):
    await stream.publish(tenant_id="t1", signature="sig", alerts=[{"a": 1}, {"a": 2}])
    args = script.calls[0]["args"]
    limit, window = settings.rate_limit
    assert args[0] == settings.ingest_max_skew_seconds * 2 + 5  # nonce ttl
    assert args[1] == limit
    assert args[2] == window
    assert args[3] == settings.ingest_stream_maxlen
    assert args[4] == "t1"
    assert args[5] == 2
    assert json.loads(args[6]) == {"a": 1}
    assert json.loads(args[7]) == {"a": 2}


async def test_the_nonce_outlives_the_replay_window(script):
    """A replay of a valid request can land up to two skew windows after the
    original, so a shorter nonce TTL would leave a gap."""
    await stream.publish(tenant_id="t1", signature="sig", alerts=[{"a": 1}])
    assert script.calls[0]["args"][0] > settings.ingest_max_skew_seconds * 2


async def test_alerts_are_serialised_compactly(script):
    await stream.publish(tenant_id="t1", signature="sig", alerts=[{"b": 1, "a": 2}])
    assert script.calls[0]["args"][6] == '{"b":1,"a":2}'


async def test_the_script_caps_the_stream_length(script):
    await stream.publish(tenant_id="t1", signature="sig", alerts=[{"a": 1}])
    assert "MAXLEN" in script.source
    assert settings.ingest_stream_maxlen > 0


async def test_the_script_checks_replay_before_spending_rate_budget(script):
    """Order matters: a replayed request must not consume the tenant's budget."""
    source = script.source if hasattr(script, "source") else stream._PUBLISH_LUA
    assert source.index("SET") < source.index("INCRBY")


def test_the_script_returns_distinct_codes_for_replay_and_rate_limit():
    assert stream.Accepted.REPLAY != stream.Accepted.RATE_LIMITED
    assert stream.Accepted.REPLAY < 0 and stream.Accepted.RATE_LIMITED < 0


def test_a_valid_tenant_id_round_trips_through_the_producer():
    tenant_id = str(uuid.uuid4())
    assert stream.rate_key(tenant_id).endswith(tenant_id)
