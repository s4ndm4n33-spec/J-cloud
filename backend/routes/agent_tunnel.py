"""HTTP surface for the agent tunnel.

Owner-scoped for now — only the owner can peek at, file, or drive tickets
via the API. Both prev-J and prod-J will call these while acting as the
owner (same user_id) so their tools land here with the correct auth.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, OWNER_USER_ID
from core import agent_tunnel as at

router = APIRouter()


def _require_owner(user: dict) -> None:
    if not OWNER_USER_ID or user.get("user_id") != OWNER_USER_ID:
        raise HTTPException(status_code=403, detail="owner only")


@router.get("/agent-tunnel/whoami")
async def whoami(user: dict = Depends(get_current_user)):
    _require_owner(user)
    return {"role": at.ROLE, "self": at._SELF}


@router.get("/agent-tunnel/tickets")
async def list_tickets(
    to: str | None = None, status: str | None = None,
    limit: int = 30,
    user: dict = Depends(get_current_user),
):
    _require_owner(user)
    docs = await at.check_inbox(db, role=to, status=status, limit=limit)
    return {"tickets": docs, "count": len(docs), "self": at._SELF}


@router.get("/agent-tunnel/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    _require_owner(user)
    t = await at.get_ticket(db, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="ticket not found")
    return t


@router.post("/agent-tunnel/tickets")
async def open_ticket(payload: dict, user: dict = Depends(get_current_user)):
    _require_owner(user)
    r = await at.open_ticket(
        db,
        to=payload.get("to", ""),
        kind=payload.get("kind", ""),
        title=payload.get("title", ""),
        body=payload.get("body", ""),
        code_diff=payload.get("code_diff"),
        files_touched=payload.get("files_touched") or [],
        priority=payload.get("priority", "p1"),
        parent_ticket_id=payload.get("parent_ticket_id"),
        from_role=payload.get("from") or at._SELF,
    )
    if r.get("error"):
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@router.post("/agent-tunnel/tickets/{ticket_id}/reply")
async def reply(ticket_id: str, payload: dict,
                user: dict = Depends(get_current_user)):
    _require_owner(user)
    r = await at.reply_to(
        db, ticket_id,
        body=payload.get("body", ""),
        code_diff=payload.get("code_diff"),
        from_role=payload.get("from") or at._SELF,
    )
    if r.get("error"):
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@router.post("/agent-tunnel/tickets/{ticket_id}/status")
async def set_status(ticket_id: str, payload: dict,
                     user: dict = Depends(get_current_user)):
    _require_owner(user)
    r = await at.mark_status(
        db, ticket_id,
        new_status=payload.get("status", ""),
        note=payload.get("note"),
        from_role=payload.get("from") or at._SELF,
    )
    if r.get("error"):
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@router.post("/agent-tunnel/tickets/{ticket_id}/escalate")
async def escalate(ticket_id: str, payload: dict,
                   user: dict = Depends(get_current_user)):
    _require_owner(user)
    r = await at.escalate(
        db, ticket_id,
        reason=payload.get("reason") or "no reason given",
        from_role=payload.get("from") or at._SELF,
    )
    if r.get("error"):
        raise HTTPException(status_code=404, detail=r["error"])
    return r


@router.post("/agent-tunnel/tickets/{ticket_id}/apply")
async def apply_diff(ticket_id: str, payload: dict | None = None,
                     user: dict = Depends(get_current_user)):
    """Prev-J only. Guarded pipeline: size cap → path denylist → git apply
    --check → git apply → (optional) pytest → mark status.
    POST body: {"run_tests": true|false} — tests default OFF because the
    preview pod's uvicorn --reload kills the request when files change.
    """
    _require_owner(user)
    if at.ROLE != "prev":
        raise HTTPException(status_code=400,
                            detail="apply is only available on the preview pod")
    run_tests = bool((payload or {}).get("run_tests", False))
    r = await at.apply_diff(db, ticket_id, run_tests=run_tests)
    if r.get("error"):
        raise HTTPException(status_code=400, detail=r)
    return r


@router.post("/agent-tunnel/sync")
async def sync_now(user: dict = Depends(get_current_user)):
    _require_owner(user)
    return await at.sync_from_r2(db)
