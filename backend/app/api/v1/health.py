import asyncio
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Response, status
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import SessionLocal
from app.redis_client import get_redis

router = APIRouter(tags=["health"])

WORKER_HEARTBEAT_KEY = f"{settings.app_name}:worker:heartbeat"


def _postgres_target() -> str:
    """host:port/database, never the password.

    Reported on failure because the most common cause of `gaierror` here is a
    DATABASE_URL whose host was mangled - a password containing `/` or `@` that
    was not percent-encoded parses into the wrong host, and the error alone
    looks identical to a container that is simply down.
    """
    try:
        url = make_url(settings.database_url)
        return f"{url.host}:{url.port or 5432}/{url.database}"
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return "unparseable DATABASE_URL"


def _redis_target() -> str:
    try:
        parts = urlsplit(settings.redis_url)
        return f"{parts.hostname}:{parts.port or 6379}"
    except Exception:  # noqa: BLE001
        return "unparseable REDIS_URL"


async def _resolves(host: str | None) -> bool:
    """Does this hostname exist on our network at all?

    The single most useful bit of diagnosis here. A container that was recreated
    gets a new name, and a URL pointing at the old one fails identically to a
    wrong password once the error class is flattened. A boolean cannot leak
    anything, unlike the exception text - and this endpoint is public.
    """
    if not host:
        return False
    try:
        loop = asyncio.get_running_loop()
        await loop.getaddrinfo(host, None)
        return True
    except (OSError, ValueError):
        return False


def _host_of(url: str, *, is_postgres: bool) -> str | None:
    try:
        return make_url(url).host if is_postgres else urlsplit(url).hostname
    except Exception:  # noqa: BLE001
        return None


def _has_password(url: str, *, is_postgres: bool) -> bool:
    """Whether the URL carries credentials at all - never what they are.

    `AuthenticationError` looks identical whether the password is wrong or was
    simply left out, and the two have different fixes.
    """
    try:
        if is_postgres:
            return bool(make_url(url).password)
        return bool(urlsplit(url).password)
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return False


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
    from app.ingest.stream import stream_depth

    return {
        "status": "ok" if healthy else "degraded",
        "postgres": {
            "ok": pg_ok,
            "error": pg_err,
            "target": _postgres_target(),
            "auth": _has_password(settings.database_url, is_postgres=True),
            "resolves": await _resolves(_host_of(settings.database_url, is_postgres=True)),
        },
        "redis": {
            "ok": redis_ok,
            "error": redis_err,
            "target": _redis_target(),
            "auth": _has_password(settings.redis_url, is_postgres=False),
            "resolves": await _resolves(_host_of(settings.redis_url, is_postgres=False)),
        },
        "worker": {"alive": await _worker_alive()},
        # A growing depth with a live worker means the writer is behind; a
        # growing depth with no worker means alerts are buffering, not lost.
        "ingest_backlog": await stream_depth() if redis_ok else -1,
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
