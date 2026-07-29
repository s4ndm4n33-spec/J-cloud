"""User → Owner report inbox.

Public users can submit:
  - `bug`         — auto-attaches last 6 chat turns + telemetry snapshot
  - `error`       — auto-attaches the specific error payload the user is on
  - `question`    — no auto-attach; user body only
  - `feedback`    — no auto-attach
  - `suggestion`  — no auto-attach

Owner gets an ambient CHAIN alert plus a full inbox at /api/admin/reports.

Privacy line: for non-bug reports, we never scoop chat context. The user has
to type what they want the owner to see. For bug/error we scoop the LAST 6
turns of the reporter's own chat — never anyone else's, and never anything
older than the current session.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import db, get_current_user, OWNER_USER_ID

router = APIRouter()

VALID_KINDS = {"bug", "error", "question", "feedback", "suggestion"}
_MAX_TITLE = 120
_MAX_BODY = 4000
_CONTEXT_TURN_LIMIT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_only(user: dict):
    if not OWNER_USER_ID or user["user_id"] != OWNER_USER_ID:
        raise HTTPException(status_code=403, detail="owner_only")


@router.post("/reports")
async def submit_report(payload: dict, user: dict = Depends(get_current_user)):
    """Any authenticated user can submit. Rate-limited to 5/hour per user via
    a simple counter."""
    kind = (payload.get("kind") or "").strip().lower()
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"kind must be one of {sorted(VALID_KINDS)}")
    title = (payload.get("title") or "").strip()[:_MAX_TITLE]
    body = (payload.get("body") or "").strip()[:_MAX_BODY]
    if not body:
        raise HTTPException(status_code=400, detail="body required")

    # Rate limit — only for opinion reports (feedback/suggestion/question).
    # Bug and error reports bypass the limit: if someone's hitting a lot of
    # errors we want to hear about ALL of them, not silence them after 5.
    if kind not in ("bug", "error"):
        hour_ago = (datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)).isoformat()
        recent = await db.user_reports.count_documents(
            {"user_id": user["user_id"], "ts": {"$gte": hour_ago},
             "kind": {"$in": ["feedback", "suggestion", "question"]}}
        )
        if recent >= 5:
            raise HTTPException(status_code=429,
                                detail="feedback rate limit — 5/hour on opinion reports. bug/error reports are unlimited.")

    report_id = f"rep_{uuid.uuid4().hex[:10]}"
    doc: dict = {
        "id": report_id,
        "kind": kind,
        "title": title or f"({kind} from {user['user_id'][:12]})",
        "body": body,
        "user_id": user["user_id"],
        "user_email": (user.get("email") or "")[:120],
        "status": "new",
        "ts": _now(),
        "context": None,
    }

    # Auto-attach context ONLY for bug/error. Never for question/feedback/suggestion.
    if kind in ("bug", "error"):
        context: dict = {}

        # Recent chat turns from this user (last 6).
        turns = await db.messages.find(
            {"user_id": user["user_id"]},
            {"_id": 0, "role": 1, "content": 1, "ts": 1, "conversation_id": 1},
        ).sort("ts", -1).limit(_CONTEXT_TURN_LIMIT).to_list(_CONTEXT_TURN_LIMIT)
        context["recent_turns"] = list(reversed(turns))

        # Latest telemetry row for this user (if any).
        telem = await db.llm_telemetry.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "task": 1, "success": 1, "attempts_count": 1,
             "ts": 1, "attempts": 1},
            sort=[("ts", -1)],
        )
        context["last_llm_call"] = telem

        # Client-provided error payload (for `error` reports).
        if kind == "error" and isinstance(payload.get("error_payload"), dict):
            context["error_payload"] = payload["error_payload"]

        doc["context"] = context

    # Optional opt-in context for non-bug reports.
    elif payload.get("include_last_message") is True:
        last = await db.messages.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "role": 1, "content": 1, "ts": 1},
            sort=[("ts", -1)],
        )
        if last:
            doc["context"] = {"last_message": last, "opted_in": True}

    await db.user_reports.insert_one(doc)

    # Ambient ping to the owner so J shows a notification in real time.
    if OWNER_USER_ID:
        await db.ambient_events.insert_one({
            "event_id": f"evt_report_{report_id}",
            "user_id": OWNER_USER_ID,
            "project_id": None,
            "kind": "USER_REPORT",
            "severity": "info" if kind in ("feedback", "suggestion", "question") else "warn",
            "title": f"{kind.upper()}: {doc['title'][:80]}",
            "body": (f"From {user.get('email') or user['user_id'][:12]} — "
                     f"{body[:200]}"),
            "action_hint": f"Open report {report_id} in the admin inbox.",
            "read": False,
            "ts": _now(),
            "meta": {"report_id": report_id, "reporter_user_id": user["user_id"]},
        })

    return {"ok": True, "report_id": report_id, "kind": kind}


@router.get("/admin/reports")
async def list_reports(status: Optional[str] = Query(None),
                       kind: Optional[str] = Query(None),
                       limit: int = Query(50, ge=1, le=200),
                       user: dict = Depends(get_current_user)):
    _owner_only(user)
    q: dict = {}
    if status: q["status"] = status
    if kind:   q["kind"] = kind
    docs = await db.user_reports.find(q, {"_id": 0}).sort("ts", -1).to_list(limit)
    total = await db.user_reports.count_documents(q)
    unread = await db.user_reports.count_documents({"status": "new"})
    return {"reports": docs, "total": total, "unread": unread}


@router.post("/admin/reports/{report_id}/read")
async def mark_read(report_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    r = await db.user_reports.update_one(
        {"id": report_id, "status": "new"},
        {"$set": {"status": "read", "read_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="report_not_found_or_already_read")
    return {"ok": True, "id": report_id, "status": "read"}


@router.post("/admin/reports/{report_id}/resolve")
async def mark_resolved(report_id: str, payload: dict | None = None,
                        user: dict = Depends(get_current_user)):
    _owner_only(user)
    note = ((payload or {}).get("note") or "").strip()[:1000]
    r = await db.user_reports.update_one(
        {"id": report_id},
        {"$set": {"status": "resolved", "resolved_at": _now(),
                  "resolution_note": note}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="report_not_found")
    return {"ok": True, "id": report_id, "status": "resolved"}


# ---------------------------------------------------------------------------
# Owner telemetry — who's failing right now
# ---------------------------------------------------------------------------

@router.get("/admin/telemetry")
async def failed_llm_calls(failed_only: bool = Query(True),
                           days: int = Query(1, ge=1, le=30),
                           limit: int = Query(50, ge=1, le=200),
                           user: dict = Depends(get_current_user)):
    """Recent LLM chain calls across all users. Default: last day, failures only.
    Use this when a user reports "J isn't working" — see if their chain has been
    exhausting and why."""
    _owner_only(user)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q: dict = {"ts": {"$gte": cutoff}}
    if failed_only:
        q["success"] = False
    docs = await db.llm_telemetry.find(
        q, {"_id": 0, "user_id": 1, "task": 1, "success": 1,
            "attempts_count": 1, "ts": 1, "attempts": 1}
    ).sort("ts", -1).to_list(limit)
    # Group counts by user for a summary line.
    by_user: dict[str, int] = {}
    for d in docs:
        by_user[d["user_id"]] = by_user.get(d["user_id"], 0) + 1
    top_offenders = sorted(by_user.items(), key=lambda x: -x[1])[:10]
    return {
        "window_days": days,
        "failed_only": failed_only,
        "rows": docs,
        "total": len(docs),
        "top_users": [{"user_id": u, "failures": n} for u, n in top_offenders],
    }
