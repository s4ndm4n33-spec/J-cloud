"""Owner-only admin surface.

- `GET  /api/admin/flags`         — recent abuse-flag rows (paginated)
- `GET  /api/admin/flags/summary` — 7-day rollup by category + top offenders

Auth: every route is guarded by `_owner_only()` — a 403 for any non-owner
user_id, no exceptions. Keep this route file thin; the actual data lives
in `db.moderation_flags` written by `core/guardrails.log_flag`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, OWNER_USER_ID

router = APIRouter()


def _owner_only(user: dict) -> None:
    if not OWNER_USER_ID or user["user_id"] != OWNER_USER_ID:
        raise HTTPException(status_code=403, detail="owner_only")


@router.get("/admin/flags")
async def list_flags(
    limit: int = 100,
    category: str | None = None,
    user_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Recent flags, newest first. Owner-only."""
    _owner_only(user)
    limit = max(1, min(int(limit), 500))
    q: dict = {}
    if category:
        q["category"] = category
    if user_id:
        q["user_id"] = user_id
    docs = await db.moderation_flags.find(q, {"_id": 0}).sort("ts", -1).to_list(limit)
    return {"flags": docs, "count": len(docs)}


@router.get("/admin/flags/summary")
async def flags_summary(user: dict = Depends(get_current_user)):
    """7-day rollup: totals by category + top 10 offending user_ids.
    One glance at Sunday morning."""
    _owner_only(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    match = {"$match": {"ts": {"$gte": cutoff}}}

    by_category = await db.moderation_flags.aggregate([
        match,
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]).to_list(20)

    top_users = await db.moderation_flags.aggregate([
        match,
        {"$group": {
            "_id": "$user_id",
            "count": {"$sum": 1},
            "categories": {"$addToSet": "$category"},
            "last_seen": {"$max": "$ts"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]).to_list(10)

    total = sum(row["count"] for row in by_category)
    return {
        "window_days": 7,
        "total_flags": total,
        "by_category": [{"category": r["_id"], "count": r["count"]} for r in by_category],
        "top_users": [
            {
                "user_id": r["_id"],
                "count": r["count"],
                "categories": r.get("categories", []),
                "last_seen": r.get("last_seen"),
            }
            for r in top_users
        ],
    }
