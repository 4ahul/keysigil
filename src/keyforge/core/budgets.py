from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keyforge.models.budget import TokenBudget, UsageRecord, UsageStats
    from keyforge.storage.base import StorageBackend


class TokenBudgetTracker:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    async def check(
        self, key_id: str, budget: TokenBudget, requested_tokens: int = 0
    ) -> tuple[bool, int | None]:
        now = datetime.now(timezone.utc)
        stats = await self._storage.get_usage_stats(key_id, now)

        for period, limit in [
            ("per_minute", budget.per_minute),
            ("daily", budget.daily),
            ("monthly", budget.monthly),
            ("lifetime", budget.lifetime),
        ]:
            if limit is None:
                continue
            used = stats.get(period, 0)
            if used + requested_tokens > limit:
                return False, max(0, limit - used)

        tightest = self._tightest_remaining(budget, stats)
        return True, tightest

    def _tightest_remaining(
        self, budget: TokenBudget, stats: dict[str, int]
    ) -> int | None:
        remainders = []
        for period, limit in [
            ("per_minute", budget.per_minute),
            ("daily", budget.daily),
            ("monthly", budget.monthly),
            ("lifetime", budget.lifetime),
        ]:
            if limit is not None:
                remainders.append(max(0, limit - stats.get(period, 0)))
        return min(remainders) if remainders else None

    async def record(self, record: UsageRecord) -> None:
        await self._storage.record_usage(record)

    async def get_stats(self, key_id: str) -> UsageStats:
        from keyforge.models.budget import UsageStats

        now = datetime.now(timezone.utc)
        raw = await self._storage.get_usage_stats(key_id, now)
        by_model = await self._storage.get_usage_by_model(key_id)
        return UsageStats(
            key_id=key_id,
            total_tokens=raw.get("lifetime", 0),
            input_tokens=raw.get("input_lifetime", 0),
            output_tokens=raw.get("output_lifetime", 0),
            by_model=by_model,
            record_count=raw.get("count", 0),
        )
