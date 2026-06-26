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
    from pathlib import Path
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
    except Exception:
        pass
    return {"ok": True, "deleted": project_id}
