"""The ingest webhook. Public by necessity; see app/ingest/auth.py for why every
rejection looks identical from outside.

The handler validates, XADDs, and returns 202. Target is under 10 ms. There is no
database write on this path beyond the cached tenant lookup, so a degraded
Postgres does not stop a client's manager from delivering.
"""

import json
import logging

from fastapi import APIRouter, Header, Request, Response, status

from app.config import settings
from app.ingest import stream
from app.ingest.auth import SIGNATURE_PREFIX, Rejection, authenticate, client_ip

router = APIRouter(prefix="/ingest", tags=["ingest"])
log = logging.getLogger(__name__)

# Every rejection returns this, whatever actually went wrong. The reason is
# logged for us and never told to the caller.
UNAUTHORISED = {"detail": "Unauthorised."}


@router.post("/wazuh/{tenant_slug}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_wazuh(
    tenant_slug: str,
    request: Request,
    response: Response,
    x_awd_signature: str | None = Header(default=None),
    x_awd_timestamp: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if len(body) > settings.ingest_max_body_bytes:
        # Not an auth failure, and saying so is safe: the size limit is public.
        response.status_code = status.HTTP_413_CONTENT_TOO_LARGE
        return {"detail": "Payload too large."}

    source_ip = client_ip(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )

    result = await authenticate(
        slug=tenant_slug,
        body=body,
        signature_header=x_awd_signature,
        timestamp_header=x_awd_timestamp,
        source_ip=source_ip,
    )

    if result.reason is Rejection.LOOKUP_UNAVAILABLE:
        # 503, not 401: the integrator retries 5xx and abandons 4xx, so this is
        # the difference between a delayed alert and a lost one.
        log.error("ingest lookup unavailable for slug=%s", tenant_slug)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["Retry-After"] = "5"
        return {"detail": "Temporarily unable to verify this client. Retry shortly."}

    if not result.ok:
        # Logged, never returned. An attacker learns nothing about which of the
        # four checks failed, or whether the tenant even exists.
        log.warning(
            "ingest rejected: slug=%s reason=%s ip=%s",
            tenant_slug,
            result.reason.value if result.reason else "unknown",
            source_ip,
        )
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return UNAUTHORISED

    tenant = result.tenant
    assert tenant is not None  # ok=True guarantees it

    # Parsing happens only after authentication: unauthenticated input is never
    # handed to the JSON decoder in bulk.
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"detail": "Body is not valid JSON."}

    # Single object or array, from day one, so a batching sidecar can arrive
    # later without an API change.
    alerts = parsed if isinstance(parsed, list) else [parsed]
    if not alerts:
        return {"accepted": 0}
    if len(alerts) > settings.ingest_max_batch:
        response.status_code = status.HTTP_413_CONTENT_TOO_LARGE
        return {"detail": f"At most {settings.ingest_max_batch} alerts per request."}
    if not all(isinstance(alert, dict) for alert in alerts):
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"detail": "Each alert must be a JSON object."}

    signature = (x_awd_signature or "").removeprefix(SIGNATURE_PREFIX)
    queued = await stream.publish(
        tenant_id=str(tenant.id), signature=signature, alerts=alerts
    )

    if queued == stream.Accepted.REPLAY:
        log.warning("ingest replay rejected: slug=%s ip=%s", tenant_slug, source_ip)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return UNAUTHORISED

    if queued == stream.Accepted.RATE_LIMITED:
        limit, window = settings.rate_limit
        log.warning("ingest rate limited: slug=%s", tenant_slug)
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = str(window)
        return {"detail": f"Rate limit of {limit} per {window}s exceeded."}

    return {"accepted": queued}
