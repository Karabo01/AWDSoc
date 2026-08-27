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
