"""Drains the ingest stream into Postgres.

At-least-once by construction: entries are acked only after the transaction
commits, so a crash mid-batch replays the batch. That is safe because the write
is idempotent - `unique (tenant_id, wazuh_id, timestamp)` plus ON CONFLICT DO
NOTHING means a redelivered alert is a no-op rather than a duplicate row.

This is also where duplicate *alerts* are absorbed. The integrator retries on
5xx, so genuine duplicates are expected and must not be errors.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.config import settings
from app.db import SessionLocal
from app.incidents import entities as entity_store
from app.incidents.grouping import (
    AlertFacts,
    attach_or_create,
    fingerprint,
    primary_entity,
)
from app.incidents.sla import policy_for
from app.ingest.parser import parse
from app.ingest.stream import ensure_consumer_group
from app.models import Alert, IngestStat, Tenant
from app.normalisation.pipeline import normalise_alert
from app.redis_client import get_redis

log = logging.getLogger(__name__)

BATCH_SIZE = 200
BLOCK_MS = 2000
# An entry held this long by a consumer that never acked is assumed orphaned.
CLAIM_IDLE_MS = 60_000


def _row(tenant_id: uuid.UUID, alert: dict) -> dict:
    parsed = parse(alert)
    normalised = normalise_alert(alert)
    return {
        "tenant_id": tenant_id,
        "wazuh_id": parsed.wazuh_id,
        "timestamp": parsed.timestamp,
        "rule_id": parsed.rule_id,
        "rule_level": parsed.rule_level,
        "rule_desc": parsed.rule_desc,
        "rule_groups": parsed.rule_groups,
        "mitre_ids": parsed.mitre_ids,
        "mitre_tactics": parsed.mitre_tactics,
        "agent_id": parsed.agent_id,
        "agent_name": parsed.agent_name,
        "ecs": normalised.ecs,
        # Never mutated. Every normalisation failure stays replayable because of it.
        "raw": alert,
        "map_version": normalised.map_version,
        "related_ip": normalised.related_ip,
        "related_user": normalised.related_user,
        "related_host": normalised.related_host,
        "related_hash": normalised.related_hash,
        "fingerprint": fingerprint(
            tenant_id=tenant_id,
            rule_id=parsed.rule_id,
            agent_id=parsed.agent_id,
            primary_entity=primary_entity(normalised.ecs),
        ),
        "incident_id": None,
    }


async def write_batch(session: AsyncSession, entries: list[tuple[str, dict]]) -> int:
    """Returns the number of rows written. Commits."""
    rows: list[dict] = []
    sizes: dict[uuid.UUID, tuple[int, int]] = {}

    for _entry_id, fields in entries:
        try:
            tenant_id = uuid.UUID(fields["tenant_id"])
            payload = fields["alert"]
            alert = json.loads(payload)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            # Unparseable at this layer means the producer put something wrong on
            # the stream. Drop it loudly rather than wedging the consumer group.
            log.exception("discarding malformed stream entry")
            continue

        if not isinstance(alert, dict):
            log.warning("discarding stream entry whose alert is not an object")
            continue

        rows.append(_row(tenant_id, alert))
        count, size = sizes.get(tenant_id, (0, 0))
        sizes[tenant_id] = (count + 1, size + len(payload))

    if not rows:
        return 0

    statement = insert(Alert).values(rows)
    statement = statement.on_conflict_do_nothing(
        index_elements=["tenant_id", "wazuh_id", "timestamp"]
    ).returning(Alert.id, Alert.tenant_id, Alert.wazuh_id, Alert.timestamp)
    # Only rows that actually landed get grouped. A redelivered alert is a
    # no-op here, which is what keeps at-least-once delivery from inflating
    # alert_count on an incident.
    inserted = {
        (row.tenant_id, row.wazuh_id, row.timestamp): row.id
        for row in await session.execute(statement)
    }

    today = datetime.now(UTC).date()
    for tenant_id, (count, size) in sizes.items():
        stat = insert(IngestStat).values(
            tenant_id=tenant_id, day=today, alert_count=count, bytes_in=size
        )
        await session.execute(
            stat.on_conflict_do_update(
                index_elements=["tenant_id", "day"],
                set_={
                    "alert_count": IngestStat.alert_count + stat.excluded.alert_count,
                    "bytes_in": IngestStat.bytes_in + stat.excluded.bytes_in,
                },
            )
        )

    touched = await _group(session, rows, inserted)

    await session.commit()

    # After the commit. An open queue told about an incident that then rolled
    # back would refetch and find nothing, which reads as a bug to an analyst.
    for tenant_id, incident_id, number, severity, created in touched:
        await events.publish(
            tenant_id=tenant_id,
            incident_id=incident_id,
            kind="created" if created else "alert",
            number=number,
            severity=severity,
        )

    return len(rows)


async def _group(session: AsyncSession, rows: list[dict], inserted: dict) -> list[tuple]:
    """Attach each newly written alert to an incident.

    One alert at a time, in timestamp order, so `last_seen` and the evidence
    snapshot end up reflecting the real sequence rather than batch order.

    Returns what changed, for the caller to announce once the transaction has
    committed. Nothing is published from inside here.
    """
    fresh = [r for r in rows if (r["tenant_id"], r["wazuh_id"], r["timestamp"]) in inserted]
    if not fresh:
        return []

    fresh.sort(key=lambda r: r["timestamp"])

    windows: dict[uuid.UUID, int] = {}
    policies: dict[uuid.UUID, list] = {}
    # Keyed by incident so a batch of forty alerts joining one case announces it
    # once rather than forty times.
    touched: dict[uuid.UUID, tuple] = {}

    for row in fresh:
        tenant_id = row["tenant_id"]
        if tenant_id not in windows:
            tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
            if tenant is None:
                log.warning("alert for unknown tenant %s; not grouping", tenant_id)
                windows[tenant_id] = -1
                policies[tenant_id] = []
                continue
            windows[tenant_id] = tenant.grouping_window_minutes
            policies[tenant_id] = await policy_for(session, tenant_id)
        if windows[tenant_id] < 0:
            continue

        related = {
            "related_ip": row["related_ip"],
            "related_user": row["related_user"],
            "related_host": row["related_host"],
            "related_hash": row["related_hash"],
        }
        facts = AlertFacts(
            tenant_id=tenant_id,
            timestamp=row["timestamp"],
            rule_id=row["rule_id"],
            rule_level=row["rule_level"],
            rule_desc=row["rule_desc"],
            fingerprint=row["fingerprint"],
            ecs=row["ecs"],
            related=related,
            primary_entity=primary_entity(row["ecs"]),
        )

        incident, created = await attach_or_create(
            session,
            alert=facts,
            grouping_window_minutes=windows[tenant_id],
            policy=policies[tenant_id],
        )
        # `created` wins if any alert in this batch opened the case: a new
        # incident is the event worth surfacing.
        was_created = created or (touched[incident.id][4] if incident.id in touched else False)
        touched[incident.id] = (
            tenant_id,
            incident.id,
            incident.number,
            incident.severity,
            was_created,
        )

        alert_id = inserted[(tenant_id, row["wazuh_id"], row["timestamp"])]
        await session.execute(
            update(Alert)
            .where(Alert.id == alert_id, Alert.timestamp == row["timestamp"])
            .values(incident_id=incident.id)
        )

        await entity_store.upsert_and_link(
            session,
            tenant_id=tenant_id,
            incident_id=incident.id,
            related=related,
            seen_at=row["timestamp"],
            primary_value=facts.primary_entity,
        )

    return list(touched.values())


async def _drain_once(redis, consumer: str) -> int:
    """One XREADGROUP cycle. Returns rows written."""
    response = await redis.xreadgroup(
        groupname=settings.ingest_consumer_group,
        consumername=consumer,
        streams={settings.ingest_stream_key: ">"},
        count=BATCH_SIZE,
        block=BLOCK_MS,
    )
    if not response:
        return 0

    entries = [(entry_id, fields) for _stream, items in response for entry_id, fields in items]
    if not entries:
        return 0

    async with SessionLocal() as session:
        written = await write_batch(session, entries)

    # Ack only after the commit. A crash before this replays the batch, which the
    # unique constraint makes harmless.
    await redis.xack(
        settings.ingest_stream_key,
        settings.ingest_consumer_group,
        *[entry_id for entry_id, _ in entries],
    )
    return written


async def reclaim_orphans(redis, consumer: str) -> int:
    """Pick up entries a dead consumer read but never acked."""
    try:
        _cursor, entries, _deleted = await redis.xautoclaim(
            name=settings.ingest_stream_key,
            groupname=settings.ingest_consumer_group,
            consumername=consumer,
            min_idle_time=CLAIM_IDLE_MS,
            count=BATCH_SIZE,
        )
    except RedisError:
        log.exception("xautoclaim failed")
        return 0

    if not entries:
        return 0

    log.info("reclaimed %s orphaned ingest entries", len(entries))
    async with SessionLocal() as session:
        written = await write_batch(session, entries)
    await redis.xack(
        settings.ingest_stream_key,
        settings.ingest_consumer_group,
        *[entry_id for entry_id, _ in entries],
    )
    return written


async def run(consumer: str | None = None, *, stop: asyncio.Event | None = None) -> None:
    """Long-running loop. Started by the worker on boot."""
    consumer = consumer or f"writer-{uuid.uuid4().hex[:8]}"
    redis = get_redis()
    await ensure_consumer_group()
    log.info("ingest consumer %s started on %s", consumer, settings.ingest_stream_key)

    backoff = 1.0
    while stop is None or not stop.is_set():
        try:
            await reclaim_orphans(redis, consumer)
            await _drain_once(redis, consumer)
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except (SQLAlchemyError, RedisError, OSError):
            # Postgres or Redis is down. The stream buffers; back off and retry
            # rather than spinning or exiting.
            log.exception("ingest consumer error; retrying in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        except Exception:
            log.exception("unexpected ingest consumer error; retrying in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    log.info("ingest consumer %s stopped", consumer)
