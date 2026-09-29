from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from keyforge.models.budget import UsageRecord


class SQLiteStorage:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self._path)
            self._db.row_factory = aiosqlite.Row
        return self._db

    async def setup(self) -> None:
        db = await self._conn()
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                permissions TEXT NOT NULL DEFAULT '[]',
                rate_limit TEXT,
                token_budget TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                rotating_until TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_key_hash ON api_keys(key_hash);

            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_id TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                timestamp TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_records(key_id, timestamp);

            CREATE TABLE IF NOT EXISTS rate_counters (
                key TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT NOT NULL
            );
        """)
        await db.commit()

    async def store_key(self, key_data: dict[str, Any]) -> None:
        db = await self._conn()
        await db.execute(
            """INSERT INTO api_keys
               (id, name, prefix, key_hash, permissions, rate_limit, token_budget,
                expires_at, created_at, revoked_at, rotating_until, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key_data["id"],
                key_data["name"],
                key_data["prefix"],
                key_data["key_hash"],
                json.dumps(key_data.get("permissions", [])),
                json.dumps(key_data["rate_limit"]) if key_data.get("rate_limit") else None,
                json.dumps(key_data["token_budget"]) if key_data.get("token_budget") else None,
                key_data.get("expires_at"),
                key_data["created_at"],
                key_data.get("revoked_at"),
                key_data.get("rotating_until"),
                json.dumps(key_data.get("metadata", {})),
            ),
        )
        await db.commit()

    async def get_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        db = await self._conn()
        async with db.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)) as cur:
            row = await cur.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_key_by_id(self, key_id: str) -> dict[str, Any] | None:
        db = await self._conn()
        async with db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_keys(self, prefix: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        db = await self._conn()
        if prefix:
            async with db.execute(
                "SELECT * FROM api_keys WHERE prefix LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"{prefix}%", limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def revoke_key(self, key_id: str, revoked_at: datetime) -> None:
        db = await self._conn()
        await db.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ?",
            (revoked_at.isoformat(), key_id),
        )
        await db.commit()

    async def update_key(self, key_id: str, updates: dict[str, Any]) -> None:
        db = await self._conn()
        set_clauses = ", ".join(f"{k} = ?" for k in updates)
        await db.execute(
            f"UPDATE api_keys SET {set_clauses} WHERE id = ?",
            (*updates.values(), key_id),
        )
        await db.commit()

    async def record_usage(self, record: UsageRecord) -> None:
        db = await self._conn()
        await db.execute(
            """INSERT INTO usage_records (key_id, input_tokens, output_tokens, model, timestamp, metadata)
               VALUES (?,?,?,?,?,?)""",
            (
                record.key_id,
                record.input_tokens,
                record.output_tokens,
                record.model,
                record.timestamp.isoformat(),
                json.dumps(record.metadata),
            ),
        )
        await db.commit()

    async def get_usage_stats(self, key_id: str, as_of: datetime) -> dict[str, int]:
        db = await self._conn()
        now = as_of.isoformat()

        # lifetime
        async with db.execute(
            "SELECT SUM(input_tokens+output_tokens), SUM(input_tokens), SUM(output_tokens), COUNT(*) FROM usage_records WHERE key_id=?",
            (key_id,),
        ) as cur:
            row = await cur.fetchone()
        lifetime, inp_lt, out_lt, count = row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0

        # daily (UTC day)
        day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        async with db.execute(
            "SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=? AND timestamp >= ?",
            (key_id, day_start),
        ) as cur:
            row = await cur.fetchone()
        daily = row[0] or 0

        # monthly
        month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        async with db.execute(
            "SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=? AND timestamp >= ?",
            (key_id, month_start),
        ) as cur:
            row = await cur.fetchone()
        monthly = row[0] or 0

        # per_minute
        minute_start = as_of.replace(second=0, microsecond=0).isoformat()
        async with db.execute(
            "SELECT SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=? AND timestamp >= ?",
            (key_id, minute_start),
        ) as cur:
            row = await cur.fetchone()
        per_minute = row[0] or 0

        return {
            "lifetime": lifetime,
            "input_lifetime": inp_lt,
            "output_lifetime": out_lt,
            "daily": daily,
            "monthly": monthly,
            "per_minute": per_minute,
            "count": count,
        }

    async def get_usage_by_model(self, key_id: str) -> dict[str, int]:
        db = await self._conn()
        async with db.execute(
            "SELECT model, SUM(input_tokens+output_tokens) FROM usage_records WHERE key_id=? AND model IS NOT NULL GROUP BY model",
            (key_id,),
        ) as cur:
            rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    async def get_counter(self, key: str) -> int:
        db = await self._conn()
        now = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            "SELECT count FROM rate_counters WHERE key=? AND expires_at > ?", (key, now)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def increment_counter(self, key: str, ttl_seconds: int) -> int:
        db = await self._conn()
        from datetime import timedelta

        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        await db.execute(
            """INSERT INTO rate_counters (key, count, expires_at) VALUES (?,1,?)
               ON CONFLICT(key) DO UPDATE SET count=count+1, expires_at=excluded.expires_at""",
            (key, expires_at),
        )
        await db.commit()
        async with db.execute("SELECT count FROM rate_counters WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else 1

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        d = dict(row)
        for field in ("permissions", "rate_limit", "token_budget", "metadata"):
            if d.get(field) and isinstance(d[field], str):
                d[field] = json.loads(d[field])
        return d
