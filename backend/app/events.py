"""Live incident events over Redis pub/sub.

The console holds a queue open on a wall screen. Polling every thirty seconds is
what M5 shipped with; this replaces it with a push so an analyst sees a new case
land rather than discovering it half a minute later.

Three things this deliberately is not:

**Not a delivery guarantee.** Pub/sub drops messages for anyone not currently
subscribed, and that is the correct trade here. The event carries an incident id
and nothing an analyst needs to act on, so the client refetches on receipt. A
dropped event costs one refresh cycle, not a missed incident.

**Not a tenancy boundary.** Every event is published to one channel and filtered
per subscriber against the token's scope. The filter lives in the SSE route
because that is where the token is - never trust the payload for tenancy.

**Not a queue.** If Redis is unavailable, publishing fails silently and the write
that triggered it still commits. An alert that landed in Postgres but produced no
notification is a stale screen; a write rolled back because a notification failed
would be lost data.
"""

import json
import logging
import uuid
from typing import Any

from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

log = logging.getLogger(__name__)


def channel() -> str:
    return f"{settings.app_name}:events:incidents"


async def publish(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    kind: str,
    number: int | None = None,
    severity: int | None = None,
    status: str | None = None,
    redis: Any = None,
) -> None:
    """Announce an incident change. Never raises."""
    payload = {
        "kind": kind,
        "tenant_id": str(tenant_id),
        "incident_id": str(incident_id),
        "number": number,
        "severity": severity,
        "status": status,
    }
    try:
        await (redis or get_redis()).publish(channel(), json.dumps(payload))
    except (RedisError, OSError):
        # See the module docstring: a missed notification is a stale screen, and
        # a stale screen is better than a failed write.
        log.debug("could not publish incident event", exc_info=True)
