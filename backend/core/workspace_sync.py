"""Workspace sync — persist project workspaces to Cloudflare R2.

The `/app/workspaces/` directory is NOT on a persistent Kubernetes volume in
this deployment, so every redeploy nukes user code. This module snapshots
each project as a gzipped tar and stores it in R2 keyed by
`workspaces/{user_id}/{project_id}/latest.tar.gz`. On boot (or on first
access after a redeploy), if the project's disk dir is missing but Mongo
knows about a `last_r2_key`, we lazy-restore from R2 before the seeder
would otherwise re-init an empty git repo.

Hybrid persistence policy (per user request):
  - Auto-snapshot every N minutes for projects that have been touched
    (`last_activity` inside the interval + disk mtime moved since last snap)
  - Auto-snapshot on session end (chat's END SESSION button)
  - Manual `POST /api/projects/{id}/snapshot` for immediate save
  - Manual `POST /api/projects/{id}/restore` to roll back to the last snap
  - Auto-restore on project open if disk is empty but a snapshot exists

Snapshot integrity: we hash the tar bytes and skip the upload if the hash
matches `last_snapshot_hash` in Mongo — protects R2 costs when nothing
actually changed between periodic ticks.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from training import storage as r2

log = logging.getLogger("workspace_sync")

# Files / dirs we NEVER snapshot — heavy, regeneratable, or platform-specific
_EXCLUDES = {
    "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
    "env", ".ruff_cache", ".mypy_cache", "dist", "build", ".next",
    ".turbo", ".parcel-cache", ".cache",
}
_EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log")

_MAX_TARBALL_BYTES = 128 * 1024 * 1024  # 128 MB hard cap per snapshot


def _r2_key(user_id: str, project_id: str) -> str:
    return f"workspaces/{user_id}/{project_id}/latest.tar.gz"


def _filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
    """tarfile filter — drop heavy/regeneratable paths."""
    parts = Path(tarinfo.name).parts
    for excl in _EXCLUDES:
        if excl in parts:
            return None
    if tarinfo.name.endswith(_EXCLUDE_SUFFIXES):
        return None
    return tarinfo


def _make_tarball(src_dir: Path) -> bytes:
    """Serialise a directory into an in-memory gzipped tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
        tf.add(src_dir, arcname=".", filter=_filter)
    return buf.getvalue()


def _extract_tarball(data: bytes, dest_dir: Path) -> int:
    """Extract a tarball into `dest_dir` (creating it fresh). Returns file count."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        members = tf.getmembers()
        # Python 3.12+ requires filter kwarg; we honor 'data' filter for safety.
        try:
            tf.extractall(dest_dir, filter="data")
        except TypeError:
            tf.extractall(dest_dir)  # older stdlib — fine, we control the source
    return len(members)


async def snapshot_project(
    db, *, user_id: str, project_id: str, src_dir: Path,
    force: bool = False,
) -> dict:
    """Snapshot a project workspace to R2. Idempotent by hash — a repeat
    call with unchanged files is a no-op (saves R2 costs + latency).

    Set `force=True` on manual saves so the user gets clear feedback even
    if we've already snapshotted the exact same tree.
    """
    if not src_dir.exists():
        return {"ok": False, "error": "source dir missing"}
    # Serialise off the event loop — tar.gz can be CPU-heavy on big trees.
    data = await asyncio.to_thread(_make_tarball, src_dir)
    if len(data) > _MAX_TARBALL_BYTES:
        return {"ok": False, "error": f"snapshot too large ({len(data)} bytes)"}
    digest = hashlib.sha256(data).hexdigest()

    # Skip upload if nothing changed since the last snapshot.
    existing = await db.projects.find_one(
        {"project_id": project_id, "user_id": user_id},
        {"_id": 0, "last_snapshot_hash": 1, "last_r2_key": 1},
    )
    if not force and existing and existing.get("last_snapshot_hash") == digest:
        return {"ok": True, "unchanged": True, "hash": digest}

    key = _r2_key(user_id, project_id)
    # R2 upload is a blocking boto3 call — punt to a thread.
    await asyncio.to_thread(
        r2.put_bytes, key, data, "application/gzip",
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one(
        {"project_id": project_id, "user_id": user_id},
        {"$set": {
            "last_r2_key": key,
            "last_snapshot_hash": digest,
            "last_snapshot_ts": now_iso,
            "last_snapshot_bytes": len(data),
        }},
    )
    # Append a history row so users can see (later, a snapshot browser).
    await db.project_snapshots.insert_one({
        "project_id": project_id,
        "user_id": user_id,
        "r2_key": key,
        "hash": digest,
        "size_bytes": len(data),
        "ts": now_iso,
        "trigger": "manual" if force else "auto",
    })
    return {"ok": True, "hash": digest, "bytes": len(data), "ts": now_iso}


async def restore_project(
    db, *, user_id: str, project_id: str, dest_dir: Path,
) -> dict:
    """Restore the latest R2 snapshot into `dest_dir`. If no snapshot exists,
    return {ok: False, missing: True} so the caller can fall back to the
    default seeder.
    """
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user_id},
        {"_id": 0, "last_r2_key": 1},
    )
    key = (proj or {}).get("last_r2_key")
    if not key:
        return {"ok": False, "missing": True}
    data = await asyncio.to_thread(r2.get_bytes, key)
    if data is None:
        log.warning(f"snapshot key {key} not found in R2")
        return {"ok": False, "missing": True}
    file_count = await asyncio.to_thread(_extract_tarball, data, dest_dir)
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one(
        {"project_id": project_id, "user_id": user_id},
        {"$set": {"last_restore_ts": now_iso}},
    )
    return {"ok": True, "files": file_count, "bytes": len(data), "ts": now_iso}


async def touch_activity(db, *, user_id: str, project_id: str) -> None:
    """Mark a project as recently active so the periodic loop knows to snap it."""
    await db.projects.update_one(
        {"project_id": project_id, "user_id": user_id},
        {"$set": {"last_activity": datetime.now(timezone.utc).isoformat()}},
    )


async def _sync_loop(db, project_path_fn, interval_sec: int = 300,
                    stale_after_sec: int = 900) -> None:
    """Background loop — every `interval_sec`, snapshot projects that saw
    activity in the last `stale_after_sec` seconds. Skips projects whose
    hash hasn't changed (see snapshot_project's dedup)."""
    while True:
        try:
            await asyncio.sleep(interval_sec)
            if not r2.r2_configured():
                continue  # R2 not wired — periodic sync is a no-op
            cutoff = (datetime.now(timezone.utc).timestamp()
                      - stale_after_sec)
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            cur = db.projects.find(
                {"last_activity": {"$gte": cutoff_iso}},
                {"_id": 0, "project_id": 1, "user_id": 1},
            )
            count = 0
            async for p in cur:
                try:
                    src = project_path_fn(p["user_id"], p["project_id"])
                    r = await snapshot_project(
                        db, user_id=p["user_id"], project_id=p["project_id"],
                        src_dir=src,
                    )
                    if r.get("ok") and not r.get("unchanged"):
                        count += 1
                except Exception as e:
                    log.warning(f"periodic snapshot failed for "
                                f"{p['project_id']}: {e}")
            if count:
                log.info(f"workspace-sync: snapshotted {count} active projects")
        except asyncio.CancelledError:
            log.info("workspace-sync loop cancelled")
            raise
        except Exception as e:
            log.warning(f"workspace-sync loop iteration failed: {e}")


class SyncLoop:
    """Simple lifecycle wrapper — start/stop hooks for FastAPI startup/shutdown."""
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    def start(self, db, project_path_fn, interval_sec: int = 300) -> None:
        if self._task and not self._task.done():
            return
        # Only start if R2 is wired — otherwise the loop is dead weight.
        if not r2.r2_configured():
            log.info("workspace-sync: R2 not configured; periodic loop disabled")
            return
        self._task = asyncio.create_task(
            _sync_loop(db, project_path_fn, interval_sec=interval_sec)
        )
        log.info(f"workspace-sync loop started (every {interval_sec}s)")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


sync_loop = SyncLoop()
