"""Owner-only admin surface.

- `GET  /api/admin/flags`             — recent abuse-flag rows (paginated)
- `GET  /api/admin/flags/summary`     — 7-day rollup by category + top offenders
- `GET  /api/admin/chronicle_export`  — streams JSONL of chronicle rows (for backfills)
- `POST /api/admin/chronicle_import`  — bulk-upserts JSONL rows by `id`

Auth: every route is guarded by `_owner_only()` — a 403 for any non-owner
user_id, no exceptions. Keep this route file thin; the actual data lives
in `db.moderation_flags` written by `core/guardrails.log_flag`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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


# ---------------------------------------------------------------------------
# Chronicle backfill (env-to-env migration)
# ---------------------------------------------------------------------------
#
# These two endpoints exist so you can seed a fresh prod DB with data from a
# more-active preview DB (or vice-versa). Both are owner-only. No sampling,
# no filtering — you get everything or nothing, and dedup happens by `id`.


@router.get("/admin/chronicle_export")
async def chronicle_export(
    kind: str | None = Query(None, description="filter by chronicle kind (e.g. ai_answer)"),
    since: str | None = Query(None, description="ISO ts; only rows at/after this"),
    user: dict = Depends(get_current_user),
):
    """Stream chronicle_entries as JSONL for cross-env migration."""
    _owner_only(user)
    q: dict = {}
    if kind:
        q["kind"] = kind
    if since:
        q["ts"] = {"$gte": since}

    async def gen():
        async for doc in db.chronicle_entries.find(q, {"_id": 0}):
            yield (json.dumps(doc, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="chronicle_export.jsonl"'},
    )


@router.post("/admin/chronicle_import")
async def chronicle_import(request: Request,
                           user: dict = Depends(get_current_user)):
    """Bulk-upsert JSONL rows by `id`. Idempotent — running twice is safe.

    Accepts either `application/x-ndjson` (one JSON per line) or a JSON array.
    Returns counts.
    """
    _owner_only(user)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    rows: list[dict] = []
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype and "ndjson" not in ctype and body.lstrip().startswith(b"["):
        try:
            rows = json.loads(body)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"bad json array: {e}")
    else:
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip malformed line rather than fail the whole batch

    inserted = updated = skipped = 0
    for row in rows:
        rid = row.get("id")
        if not rid:
            skipped += 1
            continue
        r = await db.chronicle_entries.update_one(
            {"id": rid}, {"$set": row}, upsert=True,
        )
        if r.upserted_id is not None:
            inserted += 1
        elif r.modified_count:
            updated += 1
        else:
            skipped += 1

    return {"received": len(rows), "inserted": inserted,
            "updated": updated, "skipped_or_noop": skipped}
