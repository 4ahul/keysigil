from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from keyforge.core.engine import KeyForge

_bearer = HTTPBearer(auto_error=False)


class KeyForgeAuth:
    def __init__(
        self,
        kf: KeyForge,
        require_permissions: list[str] | None = None,
        header: str = "X-API-Key",
    ) -> None:
        self._kf = kf
        self._require = require_permissions or []
        self._header = header

    async def __call__(self, request: Request) -> None:
        key = request.headers.get(self._header) or _extract_bearer(request)
        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")

        result = await self._kf.verify(key)
        if not result.valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result.error or "invalid key")

        for perm in self._require:
            if perm not in result.permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"missing permission: {perm}",
                )

        request.state.key_id = result.key_id
        request.state.key_permissions = result.permissions


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None
