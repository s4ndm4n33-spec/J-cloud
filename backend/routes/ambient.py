"""Ambient events routes — polling endpoints for the JARVIS heartbeat pulse."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user

router = APIRouter()


@router.get("/ambient/events")
async def list_events(
    since: Optional[str] = None,
    limit: int = 30,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
):
    """Return recent ambient observations for this user, newest first.

    `since` is an ISO 8601 timestamp — anything newer is returned. When
    absent, returns the last `limit` events (default 30, capped 100).
    """
    limit = max(1, min(int(limit), 100))
    q: dict = {"user_id": user["user_id"]}
    if since:
        q["ts"] = {"$gt": since}
    if unread_only:
        q["read"] = False
    docs = await db.ambient_events.find(q, {"_id": 0}) \
        .sort("ts", -1).to_list(limit)
    unread_total = await db.ambient_events.count_documents(
        {"user_id": user["user_id"], "read": False},
    )
    return {"events": docs, "unread": unread_total}


@router.post("/ambient/events/read")
async def mark_events_read(payload: dict, user: dict = Depends(get_current_user)):
    """Mark a set of event_keys as read. Passing {"all": true} clears everything."""
    if payload.get("all"):
        r = await db.ambient_events.update_many(
            {"user_id": user["user_id"], "read": False},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"ok": True, "cleared": r.modified_count}
    keys = payload.get("event_keys") or []
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=400, detail="event_keys list required")
    r = await db.ambient_events.update_many(
        {"user_id": user["user_id"], "event_key": {"$in": [str(k) for k in keys]}},
        {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "cleared": r.modified_count}


@router.delete("/ambient/events/{event_key}")
async def dismiss_event(event_key: str, user: dict = Depends(get_current_user)):
    """Permanently remove an ambient event."""
    r = await db.ambient_events.delete_one(
        {"user_id": user["user_id"], "event_key": event_key},
    )
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}
