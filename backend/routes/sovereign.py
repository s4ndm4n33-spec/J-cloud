"""Sovereign shard health/status endpoint.

Reports the runtime profile, backend readiness, database type, auth mode,
workspace state, local LLM availability, and cloud adapter status — without
exposing any secrets.
"""
from __future__ import annotations

import os

from fastapi import APIRouter

from config import settings

router = APIRouter()


@router.get("/sovereign/status")
async def sovereign_status() -> dict:
    """Report the sovereign shard runtime state.

    Never returns secret values. Cloud adapter keys are reported as
    configured/not-configured booleans only.
    """
    db_ok = False
    try:
        from deps import db
        await db.users.count_documents({})
        db_ok = True
    except Exception:
        pass

    workspace_ok = settings.workspace_root.exists()

    llm_ok = False
    llm_url = settings.local_llm_base_url if settings.portable else ""
    if settings.portable and llm_url:
        import httpx
        # Strip trailing slash, then strip /v1 if present, then append /v1/models
        base = llm_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            async with httpx.AsyncClient(timeout=3) as http:
                r = await http.get(base + "/v1/models")
                llm_ok = r.status_code == 200
        except Exception:
            llm_ok = False

    cloud = {}
    for name in ("github", "tavily", "voice", "r2", "resend", "modal"):
        cloud[name] = {
            "enabled": name in settings.enabled_cloud_adapters,
            "available": name in settings.enabled_cloud_adapters,
        }

    return {
        "profile": "portable" if settings.portable else "cloud",
        "backend": "ready" if db_ok else "error",
        "database": "sqlite" if settings.portable else "mongo",
        "authentication": "local" if settings.portable else "oauth",
        "workspace": "ready" if workspace_ok else "error",
        "workspace_path": str(settings.workspace_root),
        "local_llm": "ready" if llm_ok else ("unavailable" if settings.portable else "n/a"),
        "local_llm_url": llm_url,
        "local_llm_model": settings.local_llm_model if settings.portable else "",
        "cloud_adapters": cloud,
        "shard_root": str(settings.shard_root) if settings.portable else "",
        "version": os.environ.get("BACKEND_VERSION", "0.9.1"),
    }
