from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TokenBudget(BaseModel):
    lifetime: int | None = None
    monthly: int | None = None
    daily: int | None = None
    per_minute: int | None = None


class UsageRecord(BaseModel):
    key_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageStats(BaseModel):
    key_id: str
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, int] = Field(default_factory=dict)
    budget_remaining: int | None = None
    budget_period: str | None = None
    reset_at: datetime | None = None
    record_count: int = 0
