import logging

from app.db import SessionLocal
from app.workers import partitions

log = logging.getLogger(__name__)


async def heartbeat(ctx) -> None:
    """60 s TTL key that /healthz reports as worker liveness."""
    from app.api.v1.health import WORKER_HEARTBEAT_KEY

    await ctx["redis_client"].set(WORKER_HEARTBEAT_KEY, "1", ex=60)


async def maintain_partitions(ctx) -> dict:
    async with SessionLocal() as session:
        result = await partitions.maintain(session)
    log.info("partition maintenance: %s", result)
    return result


async def sync_agents(ctx, tenant_id=None) -> dict:
    """Refresh every active client's agent cache.

    Hourly is deliberate. This reaches out to networks we do not control, and an
    agent roster does not change fast enough to justify hammering a client's
    manager. Each tenant is independent: one unreachable manager records its own
    `last_sync_error` and the sweep continues.
    """
    from app.wazuh import sync

    async with SessionLocal() as session:
        results = await sync.sync_all(session, tenant_id=tenant_id)

    failed = [str(r.tenant_id) for r in results if not r.ok]
    if failed:
        log.warning("agent sync: %d of %d tenants failed", len(failed), len(results))
    else:
        log.info("agent sync: %d tenants ok", len(results))
    return {
        "tenants": len(results),
        "synced": sum(r.synced for r in results),
        "removed": sum(r.removed for r in results),
        "failed": failed,
    }
