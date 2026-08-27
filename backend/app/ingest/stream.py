"""Redis Streams producer for the ingest path.

The handler validates, hands off here, and returns 202. Everything below happens
in a single Redis round trip, because the budget for the whole request is under
10 ms and Postgres is deliberately not on this path at all.

One Lua script does three things atomically:

1. **Replay rejection.** A given (tenant, signature) may be spent once. Legitimate
   retries from the integrator carry a fresh timestamp - and therefore a fresh
   signature - so this rejects captured replays without breaking the retry path.
   Duplicate *alerts* are a different problem, handled idempotently at the write
   by the unique constraint on (tenant_id, wazuh_id, timestamp).
2. **Per-tenant rate limiting.** One client's alert storm must not starve another.
3. **The XADD itself**, capped by MAXLEN so a dead worker cannot exhaust Redis.
"""

import json
import logging
from enum import IntEnum

from redis.asyncio import Redis

from app.config import settings
from app.redis_client import get_redis

log = logging.getLogger(__name__)


class Accepted(IntEnum):
    REPLAY = -2
    RATE_LIMITED = -1


# KEYS[1] replay nonce   KEYS[2] rate counter   KEYS[3] stream
# ARGV[1] nonce ttl      ARGV[2] limit          ARGV[3] window seconds
# ARGV[4] maxlen         ARGV[5] tenant_id      ARGV[6] count   ARGV[7..] payloads
_PUBLISH_LUA = """
if redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[1]) == false then
  return -2
end

local count = tonumber(ARGV[6])
local used = redis.call('INCRBY', KEYS[2], count)
if used == count then
  redis.call('EXPIRE', KEYS[2], ARGV[3])
end
if used > tonumber(ARGV[2]) then
  return -1
end

for i = 7, 6 + count do
  redis.call('XADD', KEYS[3], 'MAXLEN', '~', ARGV[4], '*',
             'tenant_id', ARGV[5], 'alert', ARGV[i])
end
return count
"""

_script = None


def _publisher(redis: Redis):
    global _script
    if _script is None:
        _script = redis.register_script(_PUBLISH_LUA)
    return _script


def replay_key(tenant_id: str, signature: str) -> str:
    return f"{settings.app_name}:seen:{tenant_id}:{signature}"


def rate_key(tenant_id: str) -> str:
    return f"{settings.app_name}:rate:{tenant_id}"


async def publish(*, tenant_id: str, signature: str, alerts: list[dict]) -> int:
    """Returns the number of alerts queued, or a negative `Accepted` code."""
    limit, window = settings.rate_limit
    # A replay can only land within twice the skew window of the original.
    nonce_ttl = settings.ingest_max_skew_seconds * 2 + 5

    payloads = [json.dumps(alert, separators=(",", ":")) for alert in alerts]
    redis = get_redis()

    return int(
        await _publisher(redis)(
            keys=[
                replay_key(tenant_id, signature),
                rate_key(tenant_id),
                settings.ingest_stream_key,
            ],
            args=[
                nonce_ttl,
                limit,
                window,
                settings.ingest_stream_maxlen,
                tenant_id,
                len(payloads),
                *payloads,
            ],
        )
    )


async def ensure_consumer_group() -> None:
    """Idempotent. MKSTREAM so the worker can start before the first alert."""
    redis = get_redis()
    try:
        await redis.xgroup_create(
            settings.ingest_stream_key,
            settings.ingest_consumer_group,
            id="0",
            mkstream=True,
        )
        log.info("created consumer group %s", settings.ingest_consumer_group)
    except Exception as exc:  # noqa: BLE001 - BUSYGROUP is the expected case
        if "BUSYGROUP" not in str(exc):
            raise


async def stream_depth() -> int:
    try:
        return int(await get_redis().xlen(settings.ingest_stream_key))
    except Exception:  # noqa: BLE001 - depth is diagnostic, never load-bearing
        return -1
