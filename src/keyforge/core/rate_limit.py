from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keyforge.storage.base import StorageBackend


class SlidingWindowLimiter:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    async def check(
        self, identifier: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, datetime]:
        now = time.time()
        current_window = int(now // window_seconds)
        elapsed = now % window_seconds

        current_key = f"rl:{identifier}:{current_window}"
        prev_key = f"rl:{identifier}:{current_window - 1}"

        current_count = await self._storage.get_counter(current_key)
        prev_count = await self._storage.get_counter(prev_key)

        # ponytail: sliding window approximation; error ~0.003% per Cloudflare research
        weighted_prev = prev_count * ((window_seconds - elapsed) / window_seconds)
        estimated_count = weighted_prev + current_count

        allowed = estimated_count < limit
        if allowed:
            await self._storage.increment_counter(current_key, window_seconds * 2)

        remaining = max(0, int(limit - estimated_count - (1 if allowed else 0)))
        reset_ts = (current_window + 1) * window_seconds
        reset_at = datetime.fromtimestamp(reset_ts, tz=timezone.utc)

        return allowed, remaining, reset_at
