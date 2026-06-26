"""Audit (100-point score), migration_log, chronos, memory routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from deps import db, get_current_user, log, project_path
from core.migration_log import log_audit, log_manual, read_log
from core.persistence import (
    associative_recall, chronos_append, chronos_read,
    heuristic_get,
)
from core.scoring import audit_project

router = APIRouter()


@router.get("/projects/{project_id}/audit")
async def project_audit(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    result = audit_project(base)
    try:
        top = result["recommendations"][0]["title"] if result.get("recommendations") else None
        log_audit(base, signer="SYSTEM", score=result["score"],
                  grade=result["grade"], top_recommendation=top)
    except (OSError, KeyError) as e:
        log.warning(f"audit log write failed: {e}")
    return result


@router.get("/projects/{project_id}/migration_log")
async def get_migration_log(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    return {"content": read_log(base), "path": ".gauntlet/migration.log.md"}


@router.post("/projects/{project_id}/migration_log")
async def add_migration_log(project_id: str, payload: dict,
                            user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    entry = log_manual(
        base,
        signer=(payload.get("signer") or user.get("name") or user.get("email") or "USER"),
        title=payload.get("title") or "Untitled milestone",
        problem=payload.get("problem", ""),
        fix=payload.get("fix", ""),
        why=payload.get("why", ""),
        next_step=payload.get("next_step", ""),
        tags=payload.get("tags") or ["manual"],
    )
    return {"ok": True, "entry": entry}


@router.get("/projects/{project_id}/chronos")
async def chronos_get(project_id: str, limit: int = 100, event_type: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    return {"entries": chronos_read(base, limit=limit, event_type=event_type)}


@router.post("/projects/{project_id}/chronos")
async def chronos_post(project_id: str, payload: dict,
                       user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    entry = chronos_append(
        base,
        event_type=payload.get("event_type", "decision"),
        file=payload.get("file"),
        action=payload.get("action", ""),
        rationale=payload.get("rationale", ""),
        master=payload.get("master", ""),
        sentiment=payload.get("sentiment", "neutral"),
        actor=payload.get("actor") or (user.get("name") or "USER"),
        extra=payload.get("extra"),
    )
    return {"ok": True, "entry": entry}


@router.get("/memory/signature")
async def memory_signature(user: dict = Depends(get_current_user)):
    return await heuristic_get(db, user["user_id"])


@router.post("/memory/recall")
async def memory_recall(payload: dict, user: dict = Depends(get_current_user)):
    q = payload.get("query", "")
    k = int(payload.get("k", 5))
    project_id = payload.get("project_id")
    if not q:
        return {"hits": []}
    hits = await associative_recall(db, user["user_id"], query=q, k=k, project_id=project_id)
    return {"hits": hits}
