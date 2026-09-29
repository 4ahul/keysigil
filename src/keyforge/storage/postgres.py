from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from keyforge.models.budget import UsageRecord


class PostgresStorage:
    """PostgreSQL backend — requires asyncpg: pip install 'keyforge[postgres]'"""

    def __init__(self, db_url: str) -> None:
        self._url = db_url
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._url)
        return self._pool

    async def setup(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prefix TEXT NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    permissions JSONB NOT NULL DEFAULT '[]',
                    rate_limit JSONB,
                    token_budget JSONB,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    rotating_until TIMESTAMPTZ,
                    metadata JSONB NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_key_hash ON api_keys(key_hash);

                CREATE TABLE IF NOT EXISTS usage_records (
                    id BIGSERIAL PRIMARY KEY,
                    key_id TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    model TEXT,
                    timestamp TIMESTAMPTZ NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_records(key_id, timestamp);

                CREATE TABLE IF NOT EXISTS rate_counters (
                    key TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL
                );
            """)

    async def store_key(self, key_data: dict[str, Any]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO api_keys
                   (id, name, prefix, key_hash, permissions, rate_limit, token_budget,
                    expires_at, created_at, revoked_at, rotating_until, metadata)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                key_data["id"], key_data["name"], key_data["prefix"], key_data["key_hash"],
                json.dumps(key_data.get("permissions", [])),
                json.dumps(key_data.get("rate_limit")) if key_data.get("rate_limit") else None,
                json.dumps(key_data.get("token_budget")) if key_data.get("token_budget") else None,
                key_data.get("expires_at"), key_data["created_at"],
                key_data.get("revoked_at"), key_data.get("rotating_until"),
                json.dumps(key_data.get("metadata", {})),
            )

    async def get_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM api_keys WHERE key_hash=$1", key_hash)
        return dict(row) if row else None

    async def get_key_by_id(self, key_id: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM api_keys WHERE id=$1", key_id)
        return dict(row) if row else None

    async def list_keys(self, prefix: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if prefix:
                rows = await conn.fetch(
                    "SELECT * FROM api_keys WHERE prefix LIKE $1 ORDER BY created_at DESC LIMIT $2",
                    f"{prefix}%", limit,
                )
            else:
                rows = await conn.fetch("SELECT * FROM api_keys ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    async def revoke_key(self, key_id: str, revoked_at: datetime) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE api_keys SET revoked_at=$1 WHERE id=$2", revoked_at, key_id)

    async def update_key(self, key_id: str, updates: dict[str, Any]) -> None:
        pool = await self._get_pool()
        keys = list(updates.keys())
        vals = list(updates.values())
        set_clause = ", ".join(f"{k}=${i+1}" for i, k in enumerate(keys))
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE api_keys SET {set_clause} WHERE id=${len(keys)+1}", *vals, key_id
            )

    async def record_usage(self, record: UsageRecord) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO usage_records (key_id, input_tokens, output_tokens, model, timestamp, metadata) VALUES ($1,$2,$3,$4,$5,$6)",
                record.key_id, record.input_tokens, record.output_tokens,
                record.model, record.timestamp, json.dumps(record.metadata),
            )

    async def get_usage_stats(self, key_id: str, as_of: datetime) -> dict[str, int]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT SUM(input_tokens+output_tokens), SUM(input_tokens), SUM(output_tokens), COUNT(*) FROM usage_records WHERE key_id=$1",
                key_id,
            )
            lifetime, inp_lt, out_lt, count = row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0

            from datetime import timedelta
            day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            minute_start = as_of.replace(second=0, microsecond=0)

            daily = (await conn.fetchval("SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=$1 AND timestamp>=$2", key_id, day_start)) or 0
            monthly = (await conn.fetchval("SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=$1 AND timestamp>=$2", key_id, month_start)) or 0
            per_minute = (await conn.fetchval("SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=$1 AND timestamp>=$2", key_id, minute_start)) or 0

        return {"lifetime": lifetime, "input_lifetime": inp_lt, "output_lifetime": out_lt, "daily": daily, "monthly": monthly, "per_minute": per_minute, "count": count}

    async def get_usage_by_model(self, key_id: str) -> dict[str, int]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT model, SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=$1 AND model IS NOT NULL GROUP BY model",
                key_id,
            )
        return {r["model"]: r["sum"] for r in rows}

    async def get_counter(self, key: str) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT count FROM rate_counters WHERE key=$1 AND expires_at > NOW()", key
            )
        return val or 0

    async def increment_counter(self, key: str, ttl_seconds: int) -> int:
        pool = await self._get_pool()
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rate_counters (key, count, expires_at) VALUES ($1, 1, $2)
                   ON CONFLICT(key) DO UPDATE SET count=rate_counters.count+1, expires_at=EXCLUDED.expires_at""",
                key, expires_at,
            )
            return await conn.fetchval("SELECT count FROM rate_counters WHERE key=$1", key) or 1
