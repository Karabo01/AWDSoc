"""Replay normalisation from `raw`.

When the mapping changes, bump `NORMALISATION_MAP_VERSION` and run this across a
time range. It re-runs the engine against the stored `raw` column and rewrites
`ecs`, the `related_*` arrays, `map_version` and the fingerprint.

Two things it must never do: mutate `raw` (that is the only reason replay is
possible at all), and touch `incident_id` (grouping is M5's, and a reprocess must
not silently re-home alerts between cases).

Note the ceiling: replay only reaches back as far as retention, 90 days.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal
from app.incidents.grouping import fingerprint, primary_entity
from app.models import Alert
from app.normalisation.pipeline import normalise_alert
from app.redis_client import get_redis

log = logging.getLogger(__name__)

BATCH = 500
PROGRESS_TTL = 86400


def progress_key(job_id: str) -> str:
    return f"{settings.app_name}:reprocess:{job_id}"


async def _publish(job_id: str, **fields) -> None:
    redis = get_redis()
    await redis.hset(progress_key(job_id), mapping={k: str(v) for k, v in fields.items()})
    await redis.expire(progress_key(job_id), PROGRESS_TTL)


async def reprocess_alerts(
    ctx,
    *,
    job_id: str,
    tenant_id: str | None,
    start: str,
    end: str,
    target_version: int | None = None,
) -> dict:
    version = target_version or settings.normalisation_map_version
    start_at = datetime.fromisoformat(start)
    end_at = datetime.fromisoformat(end)
    tenant = uuid.UUID(tenant_id) if tenant_id else None

    horizon = datetime.now(UTC) - timedelta(days=settings.alert_retention_days)
    if start_at < horizon:
        log.warning(
            "reprocess window starts before retention (%s); nothing exists that far back",
            horizon.isoformat(),
        )

    updated = 0
    failed = 0
    cursor: tuple[datetime, uuid.UUID] | None = None
    await _publish(job_id, status="running", updated=0, failed=0)

    while True:
        async with SessionLocal() as session:
            stmt = select(Alert).where(Alert.timestamp >= start_at, Alert.timestamp <= end_at)
            if tenant is not None:
                stmt = stmt.where(Alert.tenant_id == tenant)
            if cursor is not None:
                stmt = stmt.where((Alert.timestamp, Alert.id) > cursor)
            stmt = stmt.order_by(Alert.timestamp, Alert.id).limit(BATCH)

            batch = list(await session.scalars(stmt))
            if not batch:
                break

            for alert in batch:
                result = normalise_alert(alert.raw, version=version)
                if result.failed:
                    failed += 1
                await session.execute(
                    update(Alert)
                    .where(Alert.id == alert.id, Alert.timestamp == alert.timestamp)
                    .values(
                        ecs=result.ecs,
                        map_version=result.map_version,
                        related_ip=result.related_ip,
                        related_user=result.related_user,
                        related_host=result.related_host,
                        related_hash=result.related_hash,
                        fingerprint=fingerprint(
                            tenant_id=alert.tenant_id,
                            rule_id=alert.rule_id,
                            agent_id=alert.agent_id,
                            primary_entity=primary_entity(result.ecs),
                        ),
                    )
                )
                updated += 1

            await session.commit()
            cursor = (batch[-1].timestamp, batch[-1].id)

        await _publish(job_id, status="running", updated=updated, failed=failed)

    await _publish(job_id, status="done", updated=updated, failed=failed)
    log.info("reprocess %s finished: %s updated, %s failed", job_id, updated, failed)
    return {"updated": updated, "failed": failed}
