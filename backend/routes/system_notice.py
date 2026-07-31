"""System-wide downtime / announcement banner.

Owner posts a short message (optionally with an `expires_at` ISO string).
Every user's UI polls `GET /api/system-notice` every 60s and renders a
top-of-screen banner while the notice is active. Used to warn about
imminent redeploys, workspace wipes, or scheduled maintenance.

Single-active-notice model: setting a new notice supersedes the previous.
The Mongo collection keeps the history for audit.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, OWNER_USER_ID

router = APIRouter()


def _is_owner(user: dict) -> bool:
    return bool(OWNER_USER_ID) and user.get("user_id") == OWNER_USER_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/system-notice")
async def get_active_notice():
    """Public — every user reads this to render the banner. Returns the
    most recent notice that hasn't expired, or `null`. No auth required
    so the banner shows even on the sign-in screen."""
    now = _now()
    doc = await db.system_notices.find_one(
        {"active": True, "$or": [
            {"expires_at": {"$exists": False}},
            {"expires_at": None},
            {"expires_at": {"$gt": now}},
        ]},
        {"_id": 0},
        sort=[("ts", -1)],
    )
    return {"notice": doc}


@router.post("/admin/system-notice")
async def set_notice(payload: dict, user: dict = Depends(get_current_user)):
    """Owner-only. Deactivate any previous notice and post a new one.

    Payload:
        {
          "message":  "Redeploy in 5m — save your work",
          "severity": "info" | "warn" | "critical"  (default 'warn'),
          "expires_at": ISO8601 (optional; if omitted, banner stays until cleared)
        }
    """
    if not _is_owner(user):
        raise HTTPException(status_code=403, detail="owner only")
    message = (payload or {}).get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    severity = (payload or {}).get("severity", "warn")
    if severity not in {"info", "warn", "critical"}:
        severity = "warn"
    expires_at = (payload or {}).get("expires_at")
    # Deactivate any prior banner so the "single active" contract holds.
    await db.system_notices.update_many({"active": True}, {"$set": {"active": False}})
    now = _now()
    notice = {
        "notice_id": f"sn_{int(datetime.now(timezone.utc).timestamp())}",
        "message": message[:400],
        "severity": severity,
        "expires_at": expires_at,
        "active": True,
        "ts": now,
        "author_id": user["user_id"],
    }
    await db.system_notices.insert_one(dict(notice))
    notice.pop("_id", None)
    return {"ok": True, "notice": notice}


@router.delete("/admin/system-notice")
async def clear_notice(user: dict = Depends(get_current_user)):
    """Owner-only. Deactivate all active notices."""
    if not _is_owner(user):
        raise HTTPException(status_code=403, detail="owner only")
    r = await db.system_notices.update_many({"active": True}, {"$set": {"active": False}})
    return {"ok": True, "cleared": r.modified_count}
