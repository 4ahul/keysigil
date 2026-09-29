from __future__ import annotations

"""Redis-backed rate counter — use as a mixin or standalone for rate limiting only.

Combine with SQLiteStorage or PostgresStorage for full storage:
    storage = SQLiteStorage("keyforge.db")
    limiter = SlidingWindowLimiter(RedisRateLimitStorage(redis_url))
"""

from datetime import datetime
from typing import Any

from keyforge.models.budget import UsageRecord


class RedisRateLimitStorage:
    """Delegates rate counters to Redis; raises NotImplementedError for key/usage ops."""

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            from redis.asyncio import from_url
            self._client = await from_url(self._url, decode_responses=True)
        return self._client

    async def get_counter(self, key: str) -> int:
        r = await self._get_client()
        val = await r.get(key)
        return int(val) if val else 0

    async def increment_counter(self, key: str, ttl_seconds: int) -> int:
        r = await self._get_client()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
        return results[0]

    # Stub out storage methods — delegate to a real backend
    async def setup(self) -> None: raise NotImplementedError
    async def store_key(self, key_data: dict[str, Any]) -> None: raise NotImplementedError
    async def get_key_by_hash(self, key_hash: str) -> dict[str, Any] | None: raise NotImplementedError
    async def get_key_by_id(self, key_id: str) -> dict[str, Any] | None: raise NotImplementedError
    async def list_keys(self, prefix: str | None = None, limit: int = 100) -> list[dict[str, Any]]: raise NotImplementedError
    async def revoke_key(self, key_id: str, revoked_at: datetime) -> None: raise NotImplementedError
    async def update_key(self, key_id: str, updates: dict[str, Any]) -> None: raise NotImplementedError
    async def record_usage(self, record: UsageRecord) -> None: raise NotImplementedError
    async def get_usage_stats(self, key_id: str, as_of: datetime) -> dict[str, int]: raise NotImplementedError
    async def get_usage_by_model(self, key_id: str) -> dict[str, int]: raise NotImplementedError
