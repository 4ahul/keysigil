from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KeyForgeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    db_url: str = "sqlite:///keyforge.db"
    redis_url: str | None = None
    default_key_prefix: str = "kf_live"
    verify_cache_ttl: int = 120  # seconds; ponytail: simple TTL, replace with Redis if needed
    max_keys_per_list: int = 100
