from datetime import UTC, datetime

from redis.asyncio import Redis, from_url

from app.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def _revoked_key(jti: str) -> str:
    return f"{settings.app_name}:revoked:{jti}"


async def revoke_token(jti: str, expires_at: datetime) -> None:
    """Deny a refresh token for whatever life it had left."""
    ttl = int((expires_at - datetime.now(UTC)).total_seconds())
    if ttl <= 0:
        return
    await get_redis().set(_revoked_key(jti), "1", ex=ttl)


async def is_revoked(jti: str) -> bool:
    return await get_redis().exists(_revoked_key(jti)) == 1
