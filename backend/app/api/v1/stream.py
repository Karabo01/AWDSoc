"""Server-sent events for the incident queue.

Mounted before the incidents router so `/incidents/stream` is matched as a
literal rather than as a malformed incident id.

**Why the token is a query parameter here and nowhere else.** `EventSource` is
the only browser API that cannot set request headers, so an SSE endpoint either
takes its credential in the URL or is not reachable from a browser at all. The
narrow costs are real - a URL can land in a proxy log or a referrer - and are
bounded deliberately: it is the short-lived *access* token, never the refresh
token; this is the only route that accepts one this way; and the value is never
logged by the app itself. The alternative, a bespoke one-shot ticket endpoint,
adds a second credential type to the system to save very little.

Tenancy is enforced on the subscriber side, against the token's own claims. The
published payload is never trusted for scoping - it names a tenant, and that name
is used only to decide whether *this* subscriber may hear about it.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.db import get_session
from app.deps.auth import accessible_tenant_ids
from app.models import User
from app.redis_client import get_redis
from app.security import TokenError, decode_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Proxies and load balancers close a connection that has said nothing. A comment
# line is a no-op to EventSource and keeps the socket demonstrably alive.
KEEPALIVE_SECONDS = 20


async def _subscriber(session: AsyncSession, token: str) -> tuple[User, set[uuid.UUID] | None]:
    """Resolve the token to a user and the tenants they may hear about.

    None means every tenant, which only an unrestricted staff token reaches.
    """
    try:
        claims = decode_token(token, "access")
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.role != claims.role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # A staff token pinned to one client hears only that client, exactly as the
    # queue behind it shows only that client.
    if claims.scope_tenant_id is not None:
        return user, {claims.scope_tenant_id}

    if not user.is_staff:
        # Unreachable while the users table constraint holds; fail closed anyway.
        return user, set()

    allowed = await accessible_tenant_ids(session, user)
    return user, (None if allowed is None else set(allowed))


@router.get("/stream")
async def incident_stream(
    request: Request,
    session: Session,
    token: Annotated[str, Query(min_length=1)],
) -> StreamingResponse:
    user, allowed = await _subscriber(session, token)

    async def generate():
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(events.channel())
        # Tells the browser the stream is live before anything happens on it, so
        # a quiet queue is distinguishable from a broken connection.
        yield ": connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=KEEPALIVE_SECONDS
                )
                if message is None:
                    yield ": keepalive\n\n"
                    continue

                try:
                    payload = json.loads(message["data"])
                    tenant_id = uuid.UUID(payload["tenant_id"])
                except (ValueError, KeyError, TypeError):
                    log.warning("discarding malformed incident event")
                    continue

                if allowed is not None and tenant_id not in allowed:
                    continue

                yield f"event: incident\ndata: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(events.channel())
                await pubsub.aclose()

    log.debug("incident stream opened for %s", user.id)
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx and several proxies buffer a response body by default, which
            # turns a live stream into a batch delivered at disconnect.
            "X-Accel-Buffering": "no",
        },
    )
