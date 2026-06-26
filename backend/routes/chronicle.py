"""Chronicle (flight-recorder), email preferences, close-session endpoints."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from deps import db, get_current_user, project_path, require_project
from core import chronicle as chron
from core import email as emailer
from chronicle_helpers import chronicle_narrative

router = APIRouter()


@router.get("/projects/{project_id}/chronicle")
async def get_chronicle(
    project_id: str,
    session_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    await require_project(user, project_id)
    entries = await chron.list_entries(db, project_id=project_id, session_id=session_id)
    return {"entries": entries, "scope": session_id or "all"}


@router.get("/projects/{project_id}/chronicle/sessions")
async def list_chronicle_sessions(
    project_id: str, user: dict = Depends(get_current_user),
):
    await require_project(user, project_id)
    return {"sessions": await chron.list_sessions(db, project_id=project_id)}


@router.post("/projects/{project_id}/chronicle/entry")
async def append_chronicle_entry(
    project_id: str, payload: dict, user: dict = Depends(get_current_user),
):
    """Manual entry written by the user (or J via the tool layer)."""
    await require_project(user, project_id)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    body = payload.get("body") or ""
    tags = payload.get("tags") or []
    kind = payload.get("kind") or "user_note"
    signer = payload.get("signer") or "USER"
    session_id = payload.get("session_id") or f"manual_{uuid.uuid4().hex[:10]}"
    if signer not in {"USER", "J"}:
        raise HTTPException(status_code=400, detail="invalid signer")
    if kind not in {"user_note", "milestone", "narrative"}:
        raise HTTPException(status_code=400, detail="invalid kind")

    entry = await chron.append_entry(
        db, project_path(user["user_id"], project_id),
        project_id=project_id, user_id=user["user_id"], session_id=session_id,
        kind=kind, signer=signer, title=title, body=body,
        tags=[str(t) for t in tags][:8],
    )
    entry.pop("_id", None)
    return {"ok": True, "entry": entry}


@router.get("/projects/{project_id}/chronicle/export")
async def export_chronicle(
    project_id: str,
    session_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    await require_project(user, project_id)
    entries = await chron.list_entries(db, project_id=project_id, session_id=session_id)
    md = chron.render_export(entries, project_id=project_id, session_id=session_id)
    scope = session_id or "full"
    filename = f"chronicle_{project_id}_{scope}.md"
    return Response(
        content=md, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/chronicle/verify")
async def verify_chronicle(
    project_id: str, user: dict = Depends(get_current_user),
):
    """Walk the hash chain. Returns ok=true if every entry's hash recomputes cleanly."""
    await require_project(user, project_id)
    return await chron.verify_chain(db, project_id=project_id)


# ---------- Email preferences ----------

@router.get("/me/email-prefs")
async def get_email_prefs(user: dict = Depends(get_current_user)):
    return {
        "enabled": bool(user.get("email_transcripts_enabled", False)),
        "address": user.get("transcript_email_address") or user.get("email") or "",
        "resend_configured": bool(os.environ.get("RESEND_API_KEY")),
    }


@router.post("/me/email-prefs")
async def set_email_prefs(payload: dict, user: dict = Depends(get_current_user)):
    enabled = bool(payload.get("enabled", False))
    addr = (payload.get("address") or "").strip()
    if enabled and "@" not in addr:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "email_transcripts_enabled": enabled,
            "transcript_email_address": addr,
            "email_prefs_updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"ok": True, "enabled": enabled, "address": addr}


# ---------- Close chat session ----------

@router.post("/projects/{project_id}/chronicle/close-session")
async def close_chat_session(
    project_id: str, payload: dict, user: dict = Depends(get_current_user),
):
    """End a chat-mode (non-agent) conversation. Writes a J-voiced chronicle
    `session_end` entry and (if opted in) emails the transcript."""
    await require_project(user, project_id)
    conversation_id = (payload.get("conversation_id") or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id required")

    msgs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]},
        {"_id": 0, "role": 1, "content": 1, "ts": 1},
    ).sort("ts", 1).to_list(500)
    if not msgs:
        raise HTTPException(status_code=404, detail="No messages in this conversation.")

    first_user = next((m["content"] for m in msgs if m.get("role") == "user"), "")
    timeline = []
    for m in msgs[:60]:
        role = (m.get("role") or "?")[:1].upper()
        snippet = (m.get("content") or "")[:120].replace("\n", " ")
        timeline.append(f"{role}: {snippet}")

    narrative_text = await chronicle_narrative(
        user_id=user["user_id"], project_id=project_id,
        session_id=conversation_id,
        user_first_msg=first_user, tool_summary=timeline,
        final_summary="(chat session manually closed by user)",
    )
    last = await db.chronicle_entries.find_one(
        {"project_id": project_id, "session_id": conversation_id,
         "kind": "session_end"},
        sort=[("ts_ns", -1)], projection={"_id": 0, "body": 1},
    )
    narrative_body = (last or {}).get("body", "") or "(no narrative generated)"

    email_sent = False
    email_error = None
    prefs_enabled = bool(user.get("email_transcripts_enabled"))
    to_addr = (user.get("transcript_email_address") or "").strip()
    if prefs_enabled and to_addr:
        proj = await db.projects.find_one({"project_id": project_id}, {"_id": 0, "name": 1})
        html, text = emailer.render_transcript_html(
            project_name=(proj or {}).get("name") or project_id,
            session_id=conversation_id,
            narrative=narrative_body,
            messages=msgs,
        )
        result = await emailer.send_email(
            to=to_addr,
            subject=f"[Gauntlet] session transcript · {(proj or {}).get('name') or project_id}",
            html=html, text=text,
        )
        email_sent = bool(result.get("ok"))
        if not email_sent:
            email_error = result.get("error")

    return {
        "ok": True,
        "narrative": narrative_body,
        "narrative_hash": narrative_text,
        "email_attempted": prefs_enabled and bool(to_addr),
        "email_sent": email_sent,
        "email_error": email_error,
        "message_count": len(msgs),
    }
