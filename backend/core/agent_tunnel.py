"""Agent Tunnel — cross-pod ticket bus between prev-J and prod-J.

R2 is the shared substrate. Local Mongo (`agent_tunnel_tickets`) is each
pod's working copy — think `git clone`, with R2 as the remote. A periodic
sync task pulls new/updated tickets from R2 into local Mongo and pushes
locally-modified ones back. Last-write-wins by `updated_ts`.

Ticket schema:
    {
      ticket_id:   "tkt_<12hex>",
      from:        "prev-j" | "prod-j" | "user",
      to:          "prev-j" | "prod-j" | "user",
      kind:        "bug" | "proposal" | "reply" | "question",
      title:       str,
      body:        str,                    # markdown-ish
      code_diff:   str | None,             # unified diff, optional
      files_touched: [str],                # paths (or empty)
      status:      "open" | "in_progress"
                 | "ready_for_deploy" | "deployed" | "rejected",
      parent_ticket_id: str | None,        # reply threading
      priority:    "p0" | "p1" | "p2",
      created_by:  role that opened it,
      ts:          ISO,
      updated_ts:  ISO,
      history:     [{role, action, ts, note}],   # audit trail
      escalate:    bool,                    # true = needs human eyes
    }

Guardrails baked into `apply_diff`:
  - hard cap on diff size (LOC)
  - path denylist for anything that touches secrets/bootstrap
  - post-apply pytest MUST pass before status advances to ready_for_deploy
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from training import storage as r2

log = logging.getLogger("agent_tunnel")

# Environment-declared role. "prev" (preview pod) or "prod" (deployed pod).
# The two Js identify each other by this. Never inferred from URL.
ROLE = os.environ.get("AGENT_TUNNEL_ROLE", "prev").strip().lower()
if ROLE not in {"prev", "prod"}:
    log.warning(f"AGENT_TUNNEL_ROLE={ROLE!r} — expected 'prev' or 'prod'")
    ROLE = "prev"

_SELF = f"{ROLE}-j"                                  # e.g. "prev-j" or "prod-j"
_R2_PREFIX = "tunnel/tickets/"
_MAX_DIFF_LOC = 200                                  # apply_diff refuses larger
_DENY_PATH_PATTERNS = [
    re.compile(r"(^|/)\.emergent(/|$)"),             # deploy manifest, secrets
    re.compile(r"(^|/)\.env(\.|$)"),                 # any .env variant
    re.compile(r".*\.(pem|key|crt)$"),               # crypto material
    re.compile(r"(^|/)backend/deps\.py$"),           # bootstrap — self-lobotomy risk
    re.compile(r"(^|/)\.git(/|$)"),                  # never touch repo internals
    re.compile(r"(^|/)node_modules(/|$)"),           # obviously
    re.compile(r"(^|/)workspaces(/|$)"),             # user code, not J's
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _r2_key(ticket_id: str) -> str:
    return f"{_R2_PREFIX}{ticket_id}.json"


def _serialise(ticket: dict) -> bytes:
    """Deterministic JSON so identical tickets hash to identical bytes."""
    return json.dumps(ticket, sort_keys=True, separators=(",", ":")).encode()


def _path_allowed(p: str) -> bool:
    return not any(pat.search(p) for pat in _DENY_PATH_PATTERNS)


# ---------------------------------------------------------------------------
# CREATE / READ / REPLY  — the primary API surface
# ---------------------------------------------------------------------------

async def open_ticket(
    db,
    *,
    to: str,
    kind: str,
    title: str,
    body: str,
    code_diff: Optional[str] = None,
    files_touched: Optional[list[str]] = None,
    priority: str = "p1",
    parent_ticket_id: Optional[str] = None,
    from_role: Optional[str] = None,
) -> dict:
    """File a new ticket. Written to local Mongo and pushed to R2."""
    if to not in {"prev-j", "prod-j", "user"}:
        return {"error": f"invalid to={to!r}"}
    if kind not in {"bug", "proposal", "reply", "question"}:
        return {"error": f"invalid kind={kind!r}"}
    if not (title or "").strip():
        return {"error": "title required"}
    if priority not in {"p0", "p1", "p2"}:
        priority = "p1"
    author = from_role or _SELF

    ticket_id = f"tkt_{uuid.uuid4().hex[:12]}"
    now = _now()
    ticket = {
        "ticket_id": ticket_id,
        "from": author,
        "to": to,
        "kind": kind,
        "title": title[:200],
        "body": body[:20000],
        "code_diff": (code_diff[:80000] if code_diff else None),
        "files_touched": [p for p in (files_touched or []) if p][:32],
        "status": "open",
        "parent_ticket_id": parent_ticket_id,
        "priority": priority,
        "created_by": author,
        "ts": now,
        "updated_ts": now,
        "history": [{"role": author, "action": "opened", "ts": now, "note": None}],
        "escalate": False,
    }
    # Local write, then R2 push. If R2 push fails we still have the local
    # row and the periodic sync will retry.
    await db.agent_tunnel_tickets.insert_one(dict(ticket))
    try:
        await asyncio.to_thread(
            r2.put_bytes, _r2_key(ticket_id),
            _serialise(ticket), "application/json",
        )
    except Exception as e:
        log.warning(f"tunnel push to R2 failed for {ticket_id}: {e}")
    ticket.pop("_id", None)
    return {"ok": True, "ticket": ticket}


async def check_inbox(
    db, *, role: Optional[str] = None,
    status: Optional[str] = None, limit: int = 20,
) -> list[dict]:
    """List tickets addressed to `role` (defaults to self), newest first.
    Excludes tickets that have already been marked deployed/rejected unless
    explicitly filtered.
    """
    role = role or _SELF
    q: dict[str, Any] = {"to": role}
    if status:
        q["status"] = status
    else:
        q["status"] = {"$nin": ["deployed", "rejected"]}
    docs = await db.agent_tunnel_tickets.find(q, {"_id": 0}) \
        .sort("updated_ts", -1).to_list(int(limit))
    return docs


async def get_ticket(db, ticket_id: str) -> Optional[dict]:
    return await db.agent_tunnel_tickets.find_one({"ticket_id": ticket_id}, {"_id": 0})


async def reply_to(
    db, ticket_id: str, body: str,
    *, code_diff: Optional[str] = None,
    from_role: Optional[str] = None,
) -> dict:
    """Post a reply as a child ticket + append to the parent's history."""
    parent = await get_ticket(db, ticket_id)
    if not parent:
        return {"error": "ticket not found"}
    author = from_role or _SELF
    # Reply goes to the opposite party of the parent's `from` field.
    reply_to_role = parent["from"] if parent["from"] != author else parent["to"]
    r = await open_ticket(
        db,
        to=reply_to_role, kind="reply",
        title=f"re: {parent['title']}"[:200],
        body=body,
        code_diff=code_diff,
        priority=parent.get("priority", "p1"),
        parent_ticket_id=ticket_id,
        from_role=author,
    )
    # Append to parent's audit history.
    now = _now()
    await db.agent_tunnel_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$push": {"history": {"role": author, "action": "replied",
                               "ts": now, "note": r["ticket"]["ticket_id"]}},
         "$set": {"updated_ts": now}},
    )
    await _push_ticket(db, ticket_id)
    return r


async def mark_status(
    db, ticket_id: str, new_status: str,
    *, note: Optional[str] = None,
    from_role: Optional[str] = None,
) -> dict:
    valid = {"open", "in_progress", "ready_for_deploy", "deployed", "rejected"}
    if new_status not in valid:
        return {"error": f"invalid status={new_status!r}"}
    now = _now()
    r = await db.agent_tunnel_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"status": new_status, "updated_ts": now},
         "$push": {"history": {"role": from_role or _SELF,
                               "action": f"status:{new_status}",
                               "ts": now, "note": note}}},
    )
    if r.matched_count == 0:
        return {"error": "ticket not found"}
    await _push_ticket(db, ticket_id)
    return {"ok": True, "status": new_status}


async def escalate(db, ticket_id: str, reason: str,
                   *, from_role: Optional[str] = None) -> dict:
    """Flag a ticket for human review. Cross-agent-safe short-circuit —
    always callable, never auto-cleared. Only a human can clear it."""
    now = _now()
    r = await db.agent_tunnel_tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"escalate": True, "updated_ts": now},
         "$push": {"history": {"role": from_role or _SELF,
                               "action": "escalated", "ts": now, "note": reason}}},
    )
    if r.matched_count == 0:
        return {"error": "ticket not found"}
    await _push_ticket(db, ticket_id)
    return {"ok": True, "escalated": True}


# ---------------------------------------------------------------------------
# APPLY DIFF — prev-J only, guarded to hell.
# ---------------------------------------------------------------------------

async def apply_diff(db, ticket_id: str, *, repo_root: str = "/app",
                     run_tests: bool = False) -> dict:
    """Apply a ticket's code_diff to the preview repo. Fails closed on any
    guardrail miss — auto-escalates instead of silently rejecting so a
    human still sees the attempt in the inbox.

    KNOWN DEV LIMITATION — preview pod only:
        uvicorn runs with `--reload` in the preview environment. The moment
        `git apply` drops a new/changed file inside `/app/backend/`,
        watchfiles triggers a process restart and this in-flight HTTP
        request is killed before it can return. Production has no reload,
        so apply_diff works end-to-end there. In preview you have two
        options:
          - target files outside `/app/backend/` (docs, frontend, serving)
          - call apply_diff from OUTSIDE the pod (curl from your machine
            or from prod-J) so the handler doesn't die with its own process

    `run_tests=False` (default) lands the diff and advances status to
    `in_progress` with a "manual verification required" note. Tests are
    skipped because the same reload race breaks the subprocess. Pass
    `run_tests=True` on the prod pod to run the smoke set inline before
    advancing to `ready_for_deploy`.
    """
    if ROLE != "prev":
        return {"error": "apply_diff is prev-J only"}

    ticket = await get_ticket(db, ticket_id)
    if not ticket:
        return {"error": "ticket not found"}
    diff = ticket.get("code_diff") or ""
    if not diff.strip():
        return {"error": "ticket has no code_diff"}
    if ticket.get("escalate"):
        return {"error": "ticket is escalated — human must clear before apply"}

    # ---- Guardrail 1: size cap ----
    loc = sum(1 for line in diff.splitlines()
              if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    if loc > _MAX_DIFF_LOC:
        await escalate(db, ticket_id,
                       f"diff too large ({loc} LOC > cap {_MAX_DIFF_LOC})")
        return {"error": "diff exceeds size cap; escalated", "loc": loc}

    # ---- Guardrail 2: path denylist ----
    paths = _extract_diff_paths(diff)
    bad = [p for p in paths if not _path_allowed(p)]
    if bad:
        await escalate(db, ticket_id, f"denied paths: {bad}")
        return {"error": f"diff touches denied paths: {bad}", "paths": bad}
    if not paths:
        await escalate(db, ticket_id, "no target paths detected in diff header")
        return {"error": "could not parse target paths from diff; escalated"}

    # ---- Guardrail 3: git must be present ----
    from shutil import which
    if not which("git"):
        await escalate(db, ticket_id, "git binary missing in runtime")
        return {"error": "git not available; escalated"}

    # ---- Apply via `git apply --check` first (dry run) ----
    check = await _run_git_apply(diff, repo_root, check_only=True)
    if not check["ok"]:
        await escalate(db, ticket_id, f"git apply --check failed: {check['stderr']}")
        return {"error": "diff does not apply cleanly; escalated",
                "stderr": check["stderr"]}

    # Real apply
    applied = await _run_git_apply(diff, repo_root, check_only=False)
    if not applied["ok"]:
        await escalate(db, ticket_id, f"git apply failed: {applied['stderr']}")
        return {"error": "apply failed after check passed; escalated",
                "stderr": applied["stderr"]}

    # ---- Optional Guardrail 4: pytest MUST pass before ready_for_deploy ----
    if not run_tests:
        await mark_status(
            db, ticket_id, "in_progress",
            note=f"applied cleanly ({loc} LOC, {len(paths)} files) — "
                 f"tests skipped; manual verification required before deploy",
        )
        return {"ok": True, "applied": True, "paths": paths, "loc": loc,
                "tests_ran": False,
                "next": "verify manually, then POST /api/agent-tunnel/tickets/{id}/status "
                        "with status=ready_for_deploy"}

    tests = await _run_pytest(repo_root)
    if not tests["ok"]:
        await escalate(db, ticket_id,
                       f"pytest failed post-apply: {tests['summary']}")
        # Revert so preview isn't left broken.
        await _run_git_apply(diff, repo_root, check_only=False, reverse=True)
        return {"error": "tests failed after apply — reverted and escalated",
                "summary": tests["summary"]}

    await mark_status(db, ticket_id, "ready_for_deploy",
                      note=f"applied cleanly, {tests['passed']} tests green")
    return {
        "ok": True, "applied": True, "paths": paths, "loc": loc,
        "tests_ran": True,
        "tests": {"passed": tests["passed"], "failed": tests["failed"]},
    }


def _extract_diff_paths(diff: str) -> list[str]:
    """Pull target paths from unified-diff headers (`+++ b/path`).
    Returns paths relative to repo root, without the b/ prefix."""
    paths = set()
    for line in diff.splitlines():
        if line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            p = line[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            paths.add(p)
    return sorted(paths)


async def _run_git_apply(diff: str, cwd: str,
                         *, check_only: bool, reverse: bool = False) -> dict:
    cmd = ["git", "apply"]
    if check_only:
        cmd.append("--check")
    if reverse:
        cmd.append("--reverse")
    cmd.append("-")  # read from stdin
    p = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await p.communicate(diff.encode())
    return {"ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace")}


async def _run_pytest(repo_root: str) -> dict:
    """Run a FAST smoke set post-apply. We deliberately DON'T run the full
    suite here — some suites hit external services and take minutes, which
    isn't appropriate for an inline apply gate. The smoke set covers the
    recent invariants (scoping, streams, eidetic memory) and is bounded to
    ~15 seconds. Fuller regression should happen in a real CI step or on
    the human's redeploy review.
    """
    env = os.environ.copy()
    # Frontend URL for tests that read it at import time.
    if "REACT_APP_BACKEND_URL" not in env:
        try:
            fe = Path(repo_root) / "frontend" / ".env"
            if fe.exists():
                for line in fe.read_text().splitlines():
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        env["REACT_APP_BACKEND_URL"] = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    smoke_targets = [
        "backend/tests/test_knowledge_scoping.py",
        "backend/tests/test_stream_error_frame.py",
        "backend/tests/test_eidetic_memory.py",
    ]
    # Include the freshly-applied test file if it landed on disk, so we
    # actually exercise the change.
    for candidate in ("backend/tests/test_tunnel_probe.py",):
        if (Path(repo_root) / candidate).exists():
            smoke_targets.append(candidate)

    try:
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pytest", *smoke_targets,
            "-q", "--no-header", "-x",  # fail fast
            cwd=repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as e:
        return {"ok": False, "returncode": -1, "passed": 0, "failed": 0,
                "summary": f"pytest spawn failed: {e}", "collection_error": False}
    try:
        stdout, stderr = await asyncio.wait_for(p.communicate(), timeout=60)
    except asyncio.TimeoutError:
        p.kill()
        return {"ok": False, "returncode": -1, "passed": 0, "failed": 0,
                "summary": "pytest wall-clock > 60s (killed)",
                "collection_error": False}

    combined = (stdout + stderr).decode(errors="replace")
    lines = [ln for ln in combined.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else "no output"
    passed = int(_first_int(summary, "passed")) if "passed" in summary else 0
    failed = int(_first_int(summary, "failed")) if "failed" in summary else 0
    return {"ok": p.returncode == 0, "returncode": p.returncode,
            "passed": passed, "failed": failed,
            "summary": summary, "collection_error": p.returncode == 2}


def _first_int(s: str, kw: str) -> str:
    m = re.search(rf"(\d+)\s+{kw}", s)
    return m.group(1) if m else "0"


# ---------------------------------------------------------------------------
# SYNC — pull from R2, push locally-modified back.
# ---------------------------------------------------------------------------

async def _push_ticket(db, ticket_id: str) -> None:
    doc = await db.agent_tunnel_tickets.find_one({"ticket_id": ticket_id}, {"_id": 0})
    if not doc:
        return
    try:
        await asyncio.to_thread(
            r2.put_bytes, _r2_key(ticket_id),
            _serialise(doc), "application/json",
        )
    except Exception as e:
        log.warning(f"tunnel push failed for {ticket_id}: {e}")


async def sync_from_r2(db) -> dict:
    """Pull every ticket from R2 and upsert into local Mongo. Last-write-wins
    on `updated_ts`. Idempotent."""
    if not r2.r2_configured():
        return {"ok": False, "reason": "r2 not configured"}
    keys = await asyncio.to_thread(_list_ticket_keys)
    pulled = 0
    for key in keys:
        try:
            raw = await asyncio.to_thread(r2.get_bytes, key)
            if not raw:
                continue
            remote = json.loads(raw)
            tid = remote.get("ticket_id")
            if not tid:
                continue
            local = await db.agent_tunnel_tickets.find_one(
                {"ticket_id": tid}, {"updated_ts": 1}
            )
            if local and local.get("updated_ts", "") >= remote.get("updated_ts", ""):
                continue
            await db.agent_tunnel_tickets.update_one(
                {"ticket_id": tid}, {"$set": remote}, upsert=True,
            )
            pulled += 1
        except Exception as e:
            log.warning(f"tunnel sync — skip {key}: {e}")
    return {"ok": True, "pulled": pulled, "keys_seen": len(keys)}


def _list_ticket_keys() -> list[str]:
    """R2/S3 list under our prefix. Sync — call via to_thread."""
    if not r2.r2_configured():
        return []
    try:
        s3 = r2._r2_client()  # type: ignore[attr-defined]
        paginator = s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(
            Bucket=os.environ.get("R2_BUCKET", ""), Prefix=_R2_PREFIX,
        ):
            for item in page.get("Contents", []) or []:
                k = item["Key"]
                if k.endswith(".json"):
                    keys.append(k)
        return keys
    except Exception as e:
        log.warning(f"tunnel list_keys failed: {e}")
        return []


async def _sync_loop(db, interval_sec: int = 30) -> None:
    while True:
        try:
            await asyncio.sleep(interval_sec)
            r = await sync_from_r2(db)
            if r.get("pulled"):
                log.info(f"tunnel sync: pulled {r['pulled']} tickets")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"tunnel sync loop failed: {e}")


class TunnelSync:
    """Lifecycle wrapper — start/stop hooks for FastAPI startup/shutdown."""
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    def start(self, db, interval_sec: int = 30) -> None:
        if self._task and not self._task.done():
            return
        if not r2.r2_configured():
            log.info("tunnel: R2 not configured; sync disabled")
            return
        self._task = asyncio.create_task(_sync_loop(db, interval_sec))
        log.info(f"agent-tunnel sync loop started ({ROLE}-j, every {interval_sec}s)")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


tunnel_sync = TunnelSync()


async def ensure_indexes(db) -> None:
    await db.agent_tunnel_tickets.create_index([("ticket_id", 1)], unique=True)
    await db.agent_tunnel_tickets.create_index([("to", 1), ("status", 1)])
    await db.agent_tunnel_tickets.create_index([("updated_ts", -1)])
    await db.agent_tunnel_tickets.create_index([("parent_ticket_id", 1)])
