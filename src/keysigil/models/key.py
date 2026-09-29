from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class KeyStatus(str, Enum):
    active = "active"
    revoked = "revoked"
    expired = "expired"
    rotating = "rotating"


class RateLimitConfig(BaseModel):
    requests: int
    window: str = "1m"  # e.g. "1m", "1h", "1d"

    @property
    def window_seconds(self) -> int:
        unit = self.window[-1]
        value = int(self.window[:-1])
        return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


class APIKey(BaseModel):
    id: str
    name: str
    prefix: str
    key_hash: str
    permissions: list[str] = Field(default_factory=list)
    rate_limit: RateLimitConfig | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: datetime | None = None
    rotating_until: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def status(self) -> KeyStatus:
        now = datetime.now(timezone.utc)
        if self.revoked_at is not None:
            return KeyStatus.revoked
        if self.expires_at is not None and now > self.expires_at:
            return KeyStatus.expired
        if self.rotating_until is not None and now < self.rotating_until:
            return KeyStatus.rotating
        return KeyStatus.active

    @property
    def is_valid(self) -> bool:
        return self.status in (KeyStatus.active, KeyStatus.rotating)

    @property
    def display(self) -> str:
        return f"{self.prefix}_****"


class KeyCreateResult(BaseModel):
    key: APIKey
    plaintext: str


class VerifyResult(BaseModel):
    valid: bool
    key_id: str | None = None
    key_name: str | None = None
    permissions: list[str] = Field(default_factory=list)
    rate_limit_remaining: int | None = None
    token_budget_remaining: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
