from typing import Any

from fastapi import APIRouter, Response, status
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import SessionLocal
from app.redis_client import get_redis

router = APIRouter(tags=["health"])

WORKER_HEARTBEAT_KEY = f"{settings.app_name}:worker:heartbeat"


async def _check_postgres() -> tuple[bool, str | None]:
    try:
        async with SessionLocal() as session:
            await session.execute(text("select 1"))
        return True, None
    except (SQLAlchemyError, OSError) as exc:
        return False, type(exc).__name__


async def _check_redis() -> tuple[bool, str | None]:
    try:
        await get_redis().ping()
        return True, None
    except (RedisError, OSError) as exc:
        return False, type(exc).__name__


async def _worker_alive() -> bool:
    try:
        return await get_redis().exists(WORKER_HEARTBEAT_KEY) == 1
    except (RedisError, OSError):
        return False


@router.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    """Coolify gates zero-downtime deploys on this. Postgres and Redis only.

    Worker liveness is reported but never fails the check.
    """
    pg_ok, pg_err = await _check_postgres()
    redis_ok, redis_err = await _check_redis()
    healthy = pg_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if healthy else "degraded",
        "postgres": {"ok": pg_ok, "error": pg_err},
        "redis": {"ok": redis_ok, "error": redis_err},
        "worker": {"alive": await _worker_alive()},
        "environment": settings.environment,
    }


@router.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Monitoring only. Never gate a deploy on a client's network being up."""
    pg_ok, _ = await _check_postgres()
    redis_ok, _ = await _check_redis()
    return {
        "postgres": pg_ok,
        "redis": redis_ok,
        "worker": await _worker_alive(),
        # Per-tenant Manager API reachability arrives with M7.
        "tenants": [],
    }
