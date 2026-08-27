"""arq worker entrypoint.

Two jobs run here: scheduled maintenance through arq's cron, and the long-lived
ingest stream consumer, which arq does not manage - it is started as a task on
boot and cancelled on shutdown.
"""

import asyncio
import logging

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.redis_client import get_redis
from app.workers import ingest_consumer
from app.workers.reprocess import reprocess_alerts
from app.workers.tasks import heartbeat, maintain_partitions

log = logging.getLogger(__name__)


async def startup(ctx) -> None:
    ctx["redis_client"] = get_redis()
    ctx["stop"] = asyncio.Event()
    ctx["ingest_task"] = asyncio.create_task(ingest_consumer.run(stop=ctx["stop"]))
    await heartbeat(ctx)


async def shutdown(ctx) -> None:
    from app.redis_client import close_redis

    stop = ctx.get("stop")
    if stop is not None:
        stop.set()
    task = ctx.get("ingest_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_redis()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [maintain_partitions, reprocess_alerts]
    cron_jobs = [
        cron(heartbeat, second={0, 30}, run_at_startup=True),
        cron(maintain_partitions, hour=3, minute=17, run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
