from __future__ import annotations

import hashlib
import re
import secrets
import uuid


_PREFIX_RE = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9]*_[A-Za-z0-9_-]+$")


def generate_key(prefix: str = "kf_live") -> str:
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}_{random_part}"


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def validate_format(key_string: str) -> bool:
    return bool(_PREFIX_RE.match(key_string))


def extract_prefix(key_string: str) -> str:
    parts = key_string.split("_")
    if len(parts) >= 3:
        return "_".join(parts[:2])
    return parts[0] if parts else ""


def new_key_id() -> str:
    return f"key_{uuid.uuid4().hex[:16]}"
