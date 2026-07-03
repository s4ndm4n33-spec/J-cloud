"""Chronicle helpers used by both chronicle routes AND ai/agent routes.

Houses the session_start auto-entry and the J-voiced narrative writer
(invokes the LLM chain). Kept separate from routes/chronicle.py so the
agent loop can import without circular dependencies.
"""
from __future__ import annotations

from typing import Optional

from deps import db, log, project_path
from core import chronicle as chron
from core.persona import CHRONICLE_PROMPT
from llm_chain import chain_call


async def chronicle_session_start(
    project_id: str, user_id: str, session_id: str, first_message: str,
) -> None:
    """Idempotent: first chat message in a conversation = session_start entry."""
    existing = await db.chronicle_entries.find_one(
        {"project_id": project_id, "session_id": session_id, "kind": "session_start"},
        {"_id": 1},
    )
    if existing:
        return
    body = first_message[:400].strip() if first_message else ""
    proot = project_path(user_id, project_id)
    try:
        await chron.append_entry(
            db, proot,
            project_id=project_id, user_id=user_id, session_id=session_id,
            kind="session_start", signer="SYSTEM",
            title=f"Session opened · {session_id[-8:]}",
            body=f"**User opened the rig and said:** {body}" if body else "",
            tags=["session"],
        )
    except Exception as e:
        log.warning(f"chronicle session_start failed: {e}")


async def chronicle_narrative(
    user_id: str, project_id: str, session_id: str,
    user_first_msg: str, tool_summary: list[str], final_summary: str,
) -> Optional[str]:
    """Call J to write a narrative paragraph; append it as a `session_end` entry."""
    timeline = "\n".join(f"- {t}" for t in tool_summary[:30]) or "- (no tool activity)"
    prompt_text = (
        f"USER ASKED: {user_first_msg[:400]}\n\n"
        f"TIMELINE OF MY WORK:\n{timeline}\n\n"
        f"FINAL SUMMARY: {final_summary[:400] or '(none)'}\n\n"
        "Write the chronicle entry now."
    )
    try:
        reply, _meta = await chain_call(
            user_id=user_id, task="chat",
            system=CHRONICLE_PROMPT, user_text=prompt_text,
            session_id=f"chronicle-{session_id}", max_passes=1,
        )
    except Exception as e:
        log.warning(f"chronicle narrative LLM call failed: {e}")
        return None
    text = (reply or "").strip()
    tags: list[str] = []
    if "\nTAGS:" in text:
        body_part, _, tag_part = text.rpartition("\nTAGS:")
        text = body_part.strip()
        tags = [t.strip().lower() for t in tag_part.split(",") if t.strip()][:4]
    proot = project_path(user_id, project_id)
    entry = await chron.append_entry(
        db, proot,
        project_id=project_id, user_id=user_id, session_id=session_id,
        kind="session_end", signer="J",
        title="Session closed",
        body=text,
        tags=tags or ["session"],
    )
    return entry["entry_hash"]
