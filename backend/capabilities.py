"""Runtime capability flags for optional cloud adapters."""
from __future__ import annotations

from fastapi import HTTPException

from config import settings


def capability_enabled(name: str) -> bool:
    return name in settings.enabled_cloud_adapters


def require_capability(name: str) -> None:
    if settings.portable and not capability_enabled(name):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "capability_unavailable",
                "capability": name,
                "message": f"{name} is disabled in portable mode",
            },
        )
