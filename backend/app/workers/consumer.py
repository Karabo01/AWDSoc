"""arq worker entrypoint.

M1 runs only the heartbeat and daily partition maintenance. The Redis Streams
alert consumer arrives with M3.
"""

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.redis_client import get_redis
from app.workers.tasks import heartbeat, maintain_partitions


async def startup(ctx) -> None:
    ctx["redis_client"] = get_redis()
    await heartbeat(ctx)


async def shutdown(ctx) -> None:
    from app.redis_client import close_redis

    await close_redis()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [maintain_partitions]
    cron_jobs = [
        cron(heartbeat, second={0, 30}, run_at_startup=True),
        cron(maintain_partitions, hour=3, minute=17, run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
