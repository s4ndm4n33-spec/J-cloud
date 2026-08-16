"""Project + file CRUD routes."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import (
    db, get_current_user, project_path, safe_join, seed_project,
    user_root, detect_language, log,
)
from core import chronicle as chron
from core import workspace_sync as wsync

router = APIRouter()


class FileReadResp(BaseModel):
    path: str
    content: str
    language: str


@router.get("/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    docs = await db.projects.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(200)
    return docs


@router.post("/projects")
async def create_project(payload: dict, user: dict = Depends(get_current_user)):
    name = (payload.get("name") or "untitled-shard").strip()
    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    path = user_root(user["user_id"]) / project_id
    seed_project(path)
    doc = {
        "project_id": project_id,
        "user_id": user["user_id"],
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.projects.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/projects/{project_id}/tree")
async def project_tree(project_id: str, user: dict = Depends(get_current_user)):
    """List a project's file tree.

    Auto-restore: if the disk dir is missing (post-redeploy on non-persistent
    volume) but a snapshot exists, pull it down BEFORE the fallback
    seeder wipes state with an empty scaffold. This is the lazy half of the
    hybrid persistence policy.
    """
    from pathlib import Path
    # Load the project row first so we know if this user actually owns it
    # and whether a snapshot exists to restore from.
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]},
        {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    from deps import user_root as _uroot
    disk = _uroot(user["user_id"]) / project_id
    if not disk.exists() and (proj.get("last_snapshot_key") or proj.get("last_r2_key")):
        try:
            r = await wsync.restore_project(
                db, user_id=user["user_id"], project_id=project_id,
                dest_dir=disk,
            )
            if r.get("ok"):
                log.info(
                    f"workspace-sync: auto-restored {project_id} "
                    f"({r.get('files')} files, {r.get('bytes')} bytes)"
                )
        except Exception as e:
            log.warning(f"auto-restore failed for {project_id}: {e}")

    base = project_path(user["user_id"], project_id)

    def walk(d: Path) -> list[dict]:
        items: list[dict] = []
        for entry in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name in (".git", "__pycache__", "node_modules", ".venv"):
                continue
            rel = entry.relative_to(base).as_posix()
            if entry.is_dir():
                items.append({"type": "dir", "name": entry.name, "path": rel, "children": walk(entry)})
            else:
                items.append({
                    "type": "file", "name": entry.name, "path": rel,
                    "size": entry.stat().st_size,
                })
        return items

    return {"project_id": project_id, "tree": walk(base)}


@router.get("/projects/{project_id}/file")
async def read_file(project_id: str, path: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    target = safe_join(base, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Binary file - not editable")
    return FileReadResp(path=path, content=content, language=detect_language(target.name))


@router.post("/projects/{project_id}/file")
async def write_file(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    path = payload.get("path", "")
    content = payload.get("content", "")
    target = safe_join(base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    # Mark this project as active so the periodic sync loop picks it up.
    try:
        await wsync.touch_activity(db, user_id=user["user_id"], project_id=project_id)
    except Exception as e:  # noqa: BLE001
        log.warning(f"workspace activity touch failed for {project_id}: {e}")
    return {"ok": True, "path": path, "bytes": len(content)}


@router.delete("/projects/{project_id}/file")
async def delete_file(project_id: str, path: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    target = safe_join(base, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True}


@router.post("/projects/{project_id}/file/rename")
async def rename_file(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    """Rename or move a file/folder within the workspace.

    Accepts {old_path, new_path}. Both are project-relative.
    """
    base = project_path(user["user_id"], project_id)
    old = (payload.get("old_path") or "").strip()
    new = (payload.get("new_path") or "").strip()
    if not old or not new:
        raise HTTPException(status_code=400, detail="old_path and new_path required")
    if old == new:
        return {"ok": True, "path": new, "unchanged": True}
    src = safe_join(base, old)
    dst = safe_join(base, new)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {old}")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {new}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"ok": True, "from": old, "to": new, "is_dir": dst.is_dir()}


@router.post("/projects/{project_id}/mkdir")
async def mkdir(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    """Create a new empty folder inside the workspace."""
    base = project_path(user["user_id"], project_id)
    path = (payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    target = safe_join(base, path)
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {path}")
    target.mkdir(parents=True, exist_ok=False)
    return {"ok": True, "path": path}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    """Permanently delete a project: workspace directory + projects doc.

    Chronicle entries are kept (audit trail). Messages are kept (user history).
    """
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_path(user["user_id"], project_id)
    if base.exists():
        try:
            shutil.rmtree(base)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"workspace delete failed: {e}") from e
    await db.projects.delete_one(
        {"project_id": project_id, "user_id": user["user_id"]},
    )
    try:
        await chron.append_entry(
            db, base.parent,
            project_id=project_id, user_id=user["user_id"],
            session_id=f"deleted_{uuid.uuid4().hex[:8]}",
            kind="milestone", signer="SYSTEM",
            title=f"Project deleted · {proj.get('name', project_id)}",
            body=f"User deleted the workspace at {base}. Chronicle preserved for audit.",
            tags=["delete", "project"],
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"project delete chronicle append failed for {project_id}: {e}")
    return {"ok": True, "deleted": project_id}


# ---------------------------------------------------------------------------
# Workspace persistence — hybrid auto+manual local/R2 sync.
# See `core/workspace_sync.py` for the tar/gzip serialisation and the
# every-5-min background loop registered in server.py.
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/snapshot")
async def snapshot_workspace(project_id: str, user: dict = Depends(get_current_user)):
    """Manual save — tar+gzip the workspace to local storage or R2. Returns
    {ok, hash, bytes, ts, unchanged}. `unchanged=True` means we detected
    no diff from the previous snapshot and skipped the upload (idempotent
    press of the SAVE button)."""
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_path(user["user_id"], project_id)
    r = await wsync.snapshot_project(
        db, user_id=user["user_id"], project_id=project_id,
        src_dir=base, force=True,
    )
    if not r.get("ok"):
        raise HTTPException(status_code=500, detail=r.get("error") or "snapshot failed")
    return r


@router.post("/projects/{project_id}/restore")
async def restore_workspace(project_id: str, user: dict = Depends(get_current_user)):
    """Manual rollback — wipe the on-disk workspace and re-hydrate from the
    latest snapshot. Destructive; users should be prompted client-side."""
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("last_r2_key"):
        if not proj.get("last_snapshot_key"):
            raise HTTPException(status_code=404, detail="No snapshot exists to restore from")
    disk = user_root(user["user_id"]) / project_id
    # Nuke existing state so extraction lands cleanly.
    if disk.exists():
        try:
            shutil.rmtree(disk)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"could not clear workspace: {e}") from e
    r = await wsync.restore_project(
        db, user_id=user["user_id"], project_id=project_id, dest_dir=disk,
    )
    if not r.get("ok"):
        raise HTTPException(status_code=500, detail="restore failed")
    return r


@router.get("/projects/{project_id}/snapshots")
async def list_snapshots(
    project_id: str, limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """Snapshot history (most recent first). Handy for a UI browser later —
    for now it powers the small 'last saved 3m ago' label in the header."""
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    docs = await db.project_snapshots.find(
        {"project_id": project_id, "user_id": user["user_id"]},
        {"_id": 0},
    ).sort("ts", -1).to_list(int(limit))
    return {
        "snapshots": docs,
        "count": len(docs),
        "latest": {
            "hash": proj.get("last_snapshot_hash"),
            "ts": proj.get("last_snapshot_ts"),
            "bytes": proj.get("last_snapshot_bytes"),
        },
    }
