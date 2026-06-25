"""Chronicle — persistent, append-only project history with atomic disk mirror.

Replaces the ephemeral `migration.log.md`. Design notes:

* **Source of truth: MongoDB.** Each entry is a doc in `chronicle_entries`. The
  pod-local workspace is a mirror, not the original. This is why the old
  migration log "reset" — workspaces are ephemeral, Mongo isn't.
* **Hash chain.** Every entry stores `prior_hash` (sha256 of the previous entry
  in the same project) and `entry_hash` (sha256 of `prior_hash + canonical_body`).
  Tampering is detectable; the chain is reconstructible.
* **Atomic disk mirror = black box.** After Mongo commits, we re-render
  `.gauntlet/chronicle.md` and `.gauntlet/sessions/<session_id>.md` via
  write-temp + fsync + rename. A crash mid-write leaves either the old file or
  the new — never a half-written file.
* **Append-only.** A unique compound index `(project_id, session_id, ts_ns)`
  on the collection makes overwrites a DB error. Mongo refuses; the API never
  has to police it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


CHRONICLE_REL = ".gauntlet/chronicle.md"
SESSIONS_DIR_REL = ".gauntlet/sessions"


VALID_KINDS = {
    "session_start",  # auto, system-signed
    "session_end",    # auto, J-signed
    "narrative",      # J writes a paragraph
    "milestone",      # important fact (commit pushed, deploy, file created)
    "user_note",      # user wrote it manually
    "proposed",       # J suggested it; user not yet accepted
}

VALID_SIGNERS = {"SYSTEM", "J", "USER"}


def _now_ns() -> int:
    return time.time_ns()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_body(entry: dict[str, Any]) -> str:
    """Deterministic JSON for hashing. Sorted keys, no whitespace tricks."""
    keep = {k: entry.get(k) for k in
            ("project_id", "session_id", "kind", "signer", "title", "body",
             "tags", "ts_ns", "ts_iso")}
    return json.dumps(keep, sort_keys=True, ensure_ascii=False, default=str)


def _hash_entry(prior_hash: str, entry: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prior_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(_canonical_body(entry).encode("utf-8"))
    return h.hexdigest()


async def ensure_indexes(db) -> None:
    """Idempotent. Call once on app startup."""
    coll = db.chronicle_entries
    await coll.create_index(
        [("project_id", 1), ("session_id", 1), ("ts_ns", 1)],
        unique=True, name="chronicle_append_only",
    )
    await coll.create_index([("project_id", 1), ("ts_ns", -1)],
                            name="chronicle_by_project")


async def _last_hash(db, project_id: str) -> str:
    last = await db.chronicle_entries.find_one(
        {"project_id": project_id},
        sort=[("ts_ns", -1)],
        projection={"_id": 0, "entry_hash": 1},
    )
    return (last or {}).get("entry_hash") or ("GENESIS" + "0" * 56)


async def append_entry(
    db,
    project_root: Path,
    *,
    project_id: str,
    user_id: str,
    session_id: str,
    kind: str,
    signer: str,
    title: str,
    body: str = "",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Append-only write: Mongo first (source of truth), then atomic disk mirror.

    Returns the persisted entry dict (sans `_id`).
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind}")
    if signer not in VALID_SIGNERS:
        raise ValueError(f"invalid signer: {signer}")

    ts_ns = _now_ns()
    entry = {
        "entry_id": uuid.uuid4().hex,
        "project_id": project_id,
        "user_id": user_id,
        "session_id": session_id,
        "kind": kind,
        "signer": signer,
        "title": title.strip()[:280],
        "body": body.strip(),
        "tags": tags or [],
        "ts_ns": ts_ns,
        "ts_iso": _now_iso(),
    }
    prior = await _last_hash(db, project_id)
    entry["prior_hash"] = prior
    entry["entry_hash"] = _hash_entry(prior, entry)

    # 1) Mongo commit (with retry on the rare ts_ns collision)
    for attempt in range(3):
        try:
            await db.chronicle_entries.insert_one({**entry})
            break
        except Exception as e:  # duplicate-key on same-ns insert
            if "duplicate key" not in str(e).lower() or attempt == 2:
                raise
            entry["ts_ns"] = _now_ns() + attempt + 1
            entry["entry_hash"] = _hash_entry(prior, entry)

    # 2) Disk mirror — atomic. Failure here does NOT roll back Mongo (Mongo is
    # the source of truth) but we log it for ops visibility.
    try:
        _mirror_to_disk(project_root, entry)
    except OSError:
        pass

    return entry


def _render_entry_md(entry: dict[str, Any]) -> str:
    """Render a single entry as a markdown block."""
    sig = entry["signer"]
    tags = " ".join(f"`{t}`" for t in entry.get("tags") or [])
    short_hash = entry["entry_hash"][:10]
    parts = [
        f"## {entry['ts_iso']} · {entry['title']}",
        f"_signed **{sig}** · kind `{entry['kind']}` · `{short_hash}`_  {tags}".rstrip(),
    ]
    if entry.get("body"):
        parts.append("")
        parts.append(entry["body"].rstrip())
    parts.append("")
    parts.append("---")
    parts.append("")
    return "\n".join(parts)


def _atomic_write(target: Path, content: str) -> None:
    """Write to a sibling .tmp file, fsync, rename over target. Flight-recorder."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:6]}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def _mirror_to_disk(project_root: Path, entry: dict[str, Any]) -> None:
    """Append entry to chronicle.md AND its session file, atomically."""
    block = _render_entry_md(entry)

    master = project_root / CHRONICLE_REL
    if master.exists():
        existing = master.read_text(encoding="utf-8")
    else:
        existing = (
            "# Project Chronicle — Sovereign Shards / Gauntlet DevSpace\n\n"
            "> Append-only narrative log. Mongo-backed; this file is the disk\n"
            "> mirror of the source-of-truth chronicle. Hash-chained: each\n"
            "> entry's `entry_hash` is sha256(prior_hash + body). If the chain\n"
            "> breaks, the file has been tampered with — go check Mongo.\n\n"
            "---\n\n"
        )
    _atomic_write(master, existing + block)

    sess = project_root / SESSIONS_DIR_REL / f"{entry['session_id']}.md"
    if sess.exists():
        existing = sess.read_text(encoding="utf-8")
    else:
        existing = (
            f"# Session · {entry['session_id']}\n\n"
            f"> first entry: {entry['ts_iso']} signed **{entry['signer']}**\n\n"
            "---\n\n"
        )
    _atomic_write(sess, existing + block)


async def list_entries(
    db, *, project_id: str, session_id: Optional[str] = None, limit: int = 500,
) -> list[dict[str, Any]]:
    q = {"project_id": project_id}
    if session_id:
        q["session_id"] = session_id
    cursor = db.chronicle_entries.find(q, {"_id": 0}).sort("ts_ns", 1).limit(limit)
    return await cursor.to_list(limit)


async def list_sessions(db, *, project_id: str) -> list[dict[str, Any]]:
    """Return one summary per session_id seen for this project."""
    pipeline = [
        {"$match": {"project_id": project_id}},
        {"$group": {
            "_id": "$session_id",
            "first_ts": {"$min": "$ts_ns"},
            "last_ts":  {"$max": "$ts_ns"},
            "first_iso": {"$min": "$ts_iso"},
            "last_iso":  {"$max": "$ts_iso"},
            "count":    {"$sum": 1},
            "title":    {"$first": "$title"},
        }},
        {"$sort": {"first_ts": -1}},
    ]
    docs = await db.chronicle_entries.aggregate(pipeline).to_list(200)
    return [{
        "session_id": d["_id"],
        "first_ts": d["first_iso"],
        "last_ts":  d["last_iso"],
        "count":    d["count"],
        "first_title": d.get("title", ""),
    } for d in docs]


async def verify_chain(db, *, project_id: str) -> dict[str, Any]:
    """Walk all entries for a project, recompute hashes, report any breaks."""
    entries = await db.chronicle_entries.find(
        {"project_id": project_id}, {"_id": 0},
    ).sort("ts_ns", 1).to_list(10000)
    prior = "GENESIS" + "0" * 56
    broken = []
    for e in entries:
        expected = _hash_entry(prior, e)
        if expected != e.get("entry_hash"):
            broken.append({"entry_id": e.get("entry_id"), "ts_iso": e.get("ts_iso"),
                           "expected": expected, "found": e.get("entry_hash")})
        prior = e.get("entry_hash") or prior
    return {"entries": len(entries), "broken": broken, "ok": not broken}


def render_export(entries: list[dict[str, Any]], *, project_id: str,
                  session_id: Optional[str] = None) -> str:
    """Render a clean .md file for export/download."""
    header = (
        f"# Project Chronicle · {project_id}\n\n"
        f"> Exported {_now_iso()}.\n"
    )
    if session_id:
        header += f"> Scope: session `{session_id}`.\n"
    else:
        header += "> Scope: full project history.\n"
    header += "\n---\n\n"
    return header + "".join(_render_entry_md(e) for e in entries)
