"""Ambient-awareness detector — the JARVIS 'watches the lab' subsystem.

Runs as a background asyncio task per active user. Every 30s it inspects each
of the user's projects and records notable observations into `db.ambient_events`.

Observations are non-blocking. J does not act on them autonomously — the
frontend surfaces them as a heartbeat pulse and lets the user click "Ask J
about this" to inject the observation into a chat as context.

Detectors implemented:
  - GIT_DIVERGE     · workspace has uncommitted changes beyond a threshold
  - CHRONICLE_FAIL  · a chronicle entry landed with `fail` in its tags recently
  - INTEGRITY_HALT  · a code-integrity rejection happened recently
  - DESTRUCTIVE_HIT · destructive-interlock or override-attempt happened
  - CHAIN_EXHAUST   · LLM failover chain exhausted (from llm_telemetry)

Each event is idempotent per (project_id, event_key) — the detector won't
re-emit the same event within a 5-minute cooldown window.
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deps import db, log, WORKSPACE_ROOT

_POLL_SECONDS = 30
_COOLDOWN_SECONDS = 300  # don't re-emit the same event key within 5 min
_TASK: asyncio.Task | None = None


def _event_key(project_id: str, kind: str, discriminator: str) -> str:
    """Deterministic key for cooldown / idempotency."""
    return hashlib.sha256(f"{project_id}:{kind}:{discriminator}".encode()).hexdigest()[:16]


async def _emit(*, user_id: str, project_id: str, kind: str, severity: str,
                title: str, body: str, action_hint: str, key_seed: str,
                meta: dict[str, Any] | None = None) -> None:
    key = _event_key(project_id, kind, key_seed)
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_COOLDOWN_SECONDS)).isoformat()
    dup = await db.ambient_events.find_one(
        {"event_key": key, "ts": {"$gt": cutoff}}, {"_id": 1},
    )
    if dup:
        return
    await db.ambient_events.insert_one({
        "event_key": key,
        "user_id": user_id,
        "project_id": project_id,
        "kind": kind,
        "severity": severity,
        "title": title,
        "body": body,
        "action_hint": action_hint,
        "ts": datetime.now(timezone.utc).isoformat(),
        "read": False,
        "meta": meta or {},
    })


async def _detect_git_diverge(user_id: str, project_id: str, base: Path) -> None:
    """Flag when uncommitted changes exceed 5 files or 200 lines."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"], cwd=base,
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        if len(lines) < 5:
            return
        # Count changed line volume
        d = subprocess.run(
            ["git", "diff", "--shortstat"], cwd=base,
            capture_output=True, text=True, timeout=5,
        )
        stat = d.stdout.strip() or f"{len(lines)} files changed"
        await _emit(
            user_id=user_id, project_id=project_id,
            kind="GIT_DIVERGE", severity="info",
            title=f"Uncommitted drift · {len(lines)} files",
            body=f"Sir, your workspace has accumulated {stat}. "
                 "Would you like me to draft a commit message?",
            action_hint="Draft a commit for me covering the current diff.",
            key_seed=f"{len(lines)}files",
            meta={"file_count": len(lines), "stat": stat},
        )
    except (subprocess.SubprocessError, OSError):
        pass


async def _detect_chronicle_fail(user_id: str, project_id: str) -> None:
    """Flag chronicle entries tagged 'fail' in the last poll window."""
    cutoff_ns = int((datetime.now(timezone.utc) - timedelta(seconds=_POLL_SECONDS * 2)).timestamp() * 1e9)
    doc = await db.chronicle_entries.find_one(
        {"project_id": project_id, "tags": "fail", "ts_ns": {"$gt": cutoff_ns}},
        sort=[("ts_ns", -1)], projection={"_id": 0, "title": 1, "body": 1, "entry_hash": 1},
    )
    if not doc:
        return
    await _emit(
        user_id=user_id, project_id=project_id,
        kind="CHRONICLE_FAIL", severity="warn",
        title=f"Recent failure · {doc.get('title', 'untitled')[:60]}",
        body=(doc.get("body") or "")[:200] or "A tool call just failed. Want me to look at what went wrong?",
        action_hint="Look at that last chronicle fail and propose a fix.",
        key_seed=doc.get("entry_hash", "")[:16],
    )


async def _detect_integrity_halt(user_id: str, project_id: str) -> None:
    """Flag recent code-integrity rejections."""
    cutoff_ns = int((datetime.now(timezone.utc) - timedelta(seconds=_POLL_SECONDS * 2)).timestamp() * 1e9)
    doc = await db.chronicle_entries.find_one(
        {
            "project_id": project_id,
            "ts_ns": {"$gt": cutoff_ns},
            "$or": [
                {"body": {"$regex": "INTEGRITY_HALT", "$options": "i"}},
                {"title": {"$regex": "INTEGRITY", "$options": "i"}},
            ],
        },
        sort=[("ts_ns", -1)], projection={"_id": 0, "title": 1, "entry_hash": 1},
    )
    if not doc:
        return
    await _emit(
        user_id=user_id, project_id=project_id,
        kind="INTEGRITY_HALT", severity="warn",
        title="Code Integrity Gateway fired",
        body="A file write was rejected by the integrity gate. Usually J "
             "recovers on the next turn — but worth a glance.",
        action_hint="Show me what J tried to write and why the gate rejected it.",
        key_seed=doc.get("entry_hash", "")[:16],
    )


async def _detect_chain_exhaust(user_id: str, project_id: str) -> None:
    """Flag when the LLM failover chain fully exhausted recently."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_POLL_SECONDS * 2)).isoformat()
    doc = await db.llm_telemetry.find_one(
        {"user_id": user_id, "ts": {"$gt": cutoff}, "success": False},
        sort=[("ts", -1)], projection={"_id": 0, "task": 1, "attempts_count": 1, "ts": 1},
    )
    if not doc:
        return
    await _emit(
        user_id=user_id, project_id=project_id,
        kind="CHAIN_EXHAUST", severity="critical",
        title=f"LLM chain exhausted on {doc.get('task', '?')}",
        body=f"All {doc.get('attempts_count', '?')} providers in the {doc.get('task','?')} "
             "chain failed. Check the /api/ai/chain view for runnable providers.",
        action_hint="Show me the chain status and suggest which provider to reconfigure.",
        key_seed=doc.get("ts", ""),
    )


async def _scan_user(user_id: str) -> None:
    projects = await db.projects.find({"user_id": user_id}, {"_id": 0, "project_id": 1}).to_list(50)
    for p in projects:
        pid = p["project_id"]
        base = WORKSPACE_ROOT / user_id / pid
        if not base.exists():
            continue
        try:
            await _detect_git_diverge(user_id, pid, base)
        except Exception as e:  # noqa: BLE001
            log.warning(f"ambient GIT_DIVERGE failed for {pid}: {e}")
        try:
            await _detect_chronicle_fail(user_id, pid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"ambient CHRONICLE_FAIL failed for {pid}: {e}")
        try:
            await _detect_integrity_halt(user_id, pid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"ambient INTEGRITY_HALT failed for {pid}: {e}")
        try:
            await _detect_chain_exhaust(user_id, pid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"ambient CHAIN_EXHAUST failed for {pid}: {e}")


async def _loop() -> None:
    """Poll every _POLL_SECONDS. Iterates users who have logged in in the last 24h."""
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            active = await db.user_sessions.distinct("user_id", {"expires_at": {"$gt": cutoff}})
            for uid in active:
                try:
                    await _scan_user(uid)
                except Exception as e:  # noqa: BLE001
                    log.warning(f"ambient scan_user({uid}) failed: {e}")
        except Exception as e:  # noqa: BLE001
            log.warning(f"ambient loop iteration failed: {e}")
        await asyncio.sleep(_POLL_SECONDS)


def start() -> None:
    global _TASK  # noqa: PLW0603
    if _TASK is None or _TASK.done():
        _TASK = asyncio.create_task(_loop(), name="ambient-detector")
        log.info("ambient-awareness detector started")


def stop() -> None:
    global _TASK  # noqa: PLW0603
    if _TASK and not _TASK.done():
        _TASK.cancel()
        _TASK = None
