from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from keyforge.core.budgets import TokenBudgetTracker
from keyforge.core.keys import extract_prefix, generate_key, hash_key, new_key_id
from keyforge.core.rate_limit import SlidingWindowLimiter
from keyforge.models.budget import TokenBudget, UsageRecord, UsageStats
from keyforge.models.config import KeyForgeConfig
from keyforge.models.key import APIKey, KeyCreateResult, RateLimitConfig, VerifyResult
from keyforge.storage.base import StorageBackend


def _make_storage(db_url: str) -> StorageBackend:
    if db_url.startswith("postgresql") or db_url.startswith("postgres"):
        from keyforge.storage.postgres import PostgresStorage
        return PostgresStorage(db_url)
    from keyforge.storage.sqlite import SQLiteStorage
    path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    return SQLiteStorage(path)


class KeyForge:
    def __init__(self, db_url: str = "sqlite:///keyforge.db", **config_kwargs: Any) -> None:
        self._config = KeyForgeConfig(db_url=db_url, **config_kwargs)
        self._storage = _make_storage(db_url)
        self._limiter = SlidingWindowLimiter(self._storage)
        self._budgets = TokenBudgetTracker(self._storage)
        self._setup_done = False

    async def setup(self) -> None:
        await self._storage.setup()
        self._setup_done = True

    def _ensure_setup(self) -> None:
        if not self._setup_done:
            raise RuntimeError("Call await kf.setup() or use `keyforge init` first.")

    async def create_key(
        self,
        name: str,
        prefix: str | None = None,
        expires_in: timedelta | None = None,
        rate_limit: dict[str, Any] | RateLimitConfig | None = None,
        token_budget: dict[str, Any] | TokenBudget | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KeyCreateResult:
        self._ensure_setup()
        pfx = prefix or self._config.default_key_prefix
        plaintext = generate_key(pfx)
        key_hash = hash_key(plaintext)
        key_id = new_key_id()
        now = datetime.now(timezone.utc)

        rl = RateLimitConfig(**rate_limit) if isinstance(rate_limit, dict) else rate_limit
        tb = TokenBudget(**token_budget) if isinstance(token_budget, dict) else token_budget

        key_data: dict[str, Any] = {
            "id": key_id,
            "name": name,
            "prefix": pfx,
            "key_hash": key_hash,
            "permissions": permissions or [],
            "rate_limit": rl.model_dump() if rl else None,
            "token_budget": tb.model_dump() if tb else None,
            "expires_at": (now + expires_in).isoformat() if expires_in else None,
            "created_at": now.isoformat(),
            "revoked_at": None,
            "rotating_until": None,
            "metadata": metadata or {},
        }
        await self._storage.store_key(key_data)

        key = APIKey(
            id=key_id,
            name=name,
            prefix=pfx,
            key_hash=key_hash,
            permissions=permissions or [],
            rate_limit=rl,
            expires_at=now + expires_in if expires_in else None,
            created_at=now,
            metadata=metadata or {},
        )
        return KeyCreateResult(key=key, plaintext=plaintext)

    async def verify(self, plaintext: str) -> VerifyResult:
        self._ensure_setup()
        key_hash = hash_key(plaintext)
        row = await self._storage.get_key_by_hash(key_hash)
        if not row:
            return VerifyResult(valid=False, error="invalid key")

        key = self._row_to_key(row)
        if not key.is_valid:
            return VerifyResult(valid=False, key_id=key.id, error=f"key is {key.status.value}")

        rate_remaining: int | None = None
        if key.rate_limit:
            allowed, remaining, _ = await self._limiter.check(
                key.id, key.rate_limit.requests, key.rate_limit.window_seconds
            )
            if not allowed:
                return VerifyResult(valid=False, key_id=key.id, error="rate limit exceeded", rate_limit_remaining=0)
            rate_remaining = remaining

        budget_remaining: int | None = None
        if row.get("token_budget"):
            tb = TokenBudget(**row["token_budget"])
            allowed, remaining = await self._budgets.check(key.id, tb)
            if not allowed:
                return VerifyResult(valid=False, key_id=key.id, error="token budget exceeded", token_budget_remaining=0)
            budget_remaining = remaining

        return VerifyResult(
            valid=True,
            key_id=key.id,
            key_name=key.name,
            permissions=key.permissions,
            rate_limit_remaining=rate_remaining,
            token_budget_remaining=budget_remaining,
        )

    async def revoke_key(self, key_id: str) -> None:
        self._ensure_setup()
        await self._storage.revoke_key(key_id, datetime.now(timezone.utc))

    async def rotate_key(
        self,
        key_id: str,
        grace_period: timedelta = timedelta(hours=24),
    ) -> KeyCreateResult:
        self._ensure_setup()
        row = await self._storage.get_key_by_id(key_id)
        if not row:
            raise ValueError(f"key not found: {key_id}")
        old_key = self._row_to_key(row)
        rotating_until = datetime.now(timezone.utc) + grace_period
        await self._storage.update_key(key_id, {"rotating_until": rotating_until.isoformat()})

        new = await self.create_key(
            name=old_key.name,
            prefix=old_key.prefix,
            permissions=old_key.permissions,
            metadata=old_key.metadata,
        )
        return new

    async def list_keys(self, prefix: str | None = None) -> list[APIKey]:
        self._ensure_setup()
        rows = await self._storage.list_keys(prefix, self._config.max_keys_per_list)
        return [self._row_to_key(r) for r in rows]

    async def track_usage(
        self,
        key_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_setup()
        record = UsageRecord(
            key_id=key_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            metadata=metadata or {},
        )
        await self._budgets.record(record)

    async def get_usage(self, key_id: str) -> UsageStats:
        self._ensure_setup()
        return await self._budgets.get_stats(key_id)

    async def update_budget(self, key_id: str, token_budget: dict[str, Any] | TokenBudget) -> None:
        self._ensure_setup()
        tb = TokenBudget(**token_budget) if isinstance(token_budget, dict) else token_budget
        await self._storage.update_key(key_id, {"token_budget": tb.model_dump_json()})

    def _row_to_key(self, row: dict[str, Any]) -> APIKey:
        rl = RateLimitConfig(**row["rate_limit"]) if row.get("rate_limit") else None
        return APIKey(
            id=row["id"],
            name=row["name"],
            prefix=row["prefix"],
            key_hash=row["key_hash"],
            permissions=row.get("permissions") or [],
            rate_limit=rl,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row.get("expires_at") else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row.get("revoked_at") else None,
            rotating_until=datetime.fromisoformat(row["rotating_until"]) if row.get("rotating_until") else None,
            metadata=row.get("metadata") or {},
        )
