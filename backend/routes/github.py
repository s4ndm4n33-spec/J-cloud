"""GitHub integration routes (PAT-based — full OAuth pending)."""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, log, project_path, user_root
from core.github_api import (
    GitHubError, create_repo, git_clone, git_current_branch, git_pull, git_push,
    git_set_remote, list_repos, open_pr, whoami,
)
from core.keyvault import decrypt_key, encrypt_key, mask

router = APIRouter()


async def _resolve_github_token(user_id: str) -> Optional[str]:
    doc = await db.user_github.find_one({"user_id": user_id}, {"_id": 0})
    if doc and doc.get("ciphertext"):
        try:
            return decrypt_key(doc["ciphertext"])
        except (ValueError, TypeError):
            log.warning(f"github token decrypt failed for {user_id}")
    return None


@router.get("/github/auth")
async def github_auth_status(user: dict = Depends(get_current_user)):
    doc = await db.user_github.find_one({"user_id": user["user_id"]}, {"_id": 0, "ciphertext": 0})
    if not doc:
        return {"connected": False}
    return {
        "connected": True,
        "method": doc.get("method", "pat"),
        "login": doc.get("login"),
        "avatar_url": doc.get("avatar_url"),
        "masked": doc.get("masked"),
        "scopes": doc.get("scopes", []),
    }


@router.post("/github/auth")
async def github_auth_pat(payload: dict, user: dict = Depends(get_current_user)):
    token = (payload.get("token") or "").strip()
    if not token or len(token) < 20:
        raise HTTPException(status_code=400, detail="Invalid GitHub token")
    try:
        me = await whoami(token)
    except GitHubError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.user_github.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "user_id": user["user_id"],
            "method": "pat",
            "ciphertext": encrypt_key(token),
            "masked": mask(token),
            "login": me.get("login"),
            "avatar_url": me.get("avatar_url"),
            "scopes": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "login": me.get("login"), "avatar_url": me.get("avatar_url")}


@router.delete("/github/auth")
async def github_auth_delete(user: dict = Depends(get_current_user)):
    await db.user_github.delete_one({"user_id": user["user_id"]})
    return {"ok": True}


@router.get("/github/repos")
async def github_repos(page: int = 1, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    try:
        repos = await list_repos(token, page=page)
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"repos": repos, "page": page}


@router.post("/github/clone")
async def github_clone_repo(payload: dict, user: dict = Depends(get_current_user)):
    """Clone a GitHub repo as a NEW workspace project."""
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    clone_url = payload.get("clone_url", "")
    full_name = payload.get("full_name") or clone_url.rsplit("/", 2)[-1].replace(".git", "")
    if not clone_url:
        raise HTTPException(status_code=400, detail="clone_url required")

    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    dest = user_root(user["user_id"]) / project_id
    code, _out, err = git_clone(token, clone_url, dest)
    if code != 0 or not dest.exists():
        raise HTTPException(status_code=500, detail=f"clone failed: {err[:300]}")

    name = payload.get("name") or full_name.split("/")[-1]
    doc = {
        "project_id": project_id,
        "user_id": user["user_id"],
        "name": name,
        "github_full_name": full_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.projects.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.post("/projects/{project_id}/github/create")
async def github_create_for_project(project_id: str, payload: dict,
                                    user: dict = Depends(get_current_user)):
    """Create a NEW GitHub repo and push the current workspace to it."""
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    name = (payload.get("name") or "").strip()
    private = bool(payload.get("private", True))
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    base = project_path(user["user_id"], project_id)
    try:
        repo = await create_repo(token, name, private, payload.get("description", ""))
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    git_set_remote(base, repo["clone_url"])
    subprocess.run(["git", "add", "."], cwd=base, capture_output=True, timeout=10)
    subprocess.run(["git", "commit", "-m", "Initial shard from Gauntlet DevSpace"],
                   cwd=base, capture_output=True, timeout=10)
    subprocess.run(["git", "branch", "-M", "main"], cwd=base, capture_output=True, timeout=5)
    code, out, err = git_push(token, base, "main", set_upstream=True)
    await db.projects.update_one(
        {"project_id": project_id, "user_id": user["user_id"]},
        {"$set": {"github_full_name": repo["full_name"]}},
    )
    return {
        "ok": code == 0,
        "repo": {"full_name": repo["full_name"], "html_url": repo["html_url"], "clone_url": repo["clone_url"]},
        "push_stdout": out, "push_stderr": err,
    }


@router.post("/projects/{project_id}/github/link")
async def github_link(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    clone_url = payload.get("clone_url") or payload.get("url", "")
    full_name = payload.get("full_name") or ""
    if not clone_url:
        raise HTTPException(status_code=400, detail="clone_url required")
    git_set_remote(base, clone_url)
    await db.projects.update_one(
        {"project_id": project_id, "user_id": user["user_id"]},
        {"$set": {"github_full_name": full_name}},
    )
    return {"ok": True}


@router.post("/projects/{project_id}/github/push")
async def github_push(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    base = project_path(user["user_id"], project_id)
    branch = payload.get("branch") or git_current_branch(base)
    code, out, err = git_push(token, base, branch, set_upstream=True)
    return {"ok": code == 0, "stdout": out, "stderr": err, "branch": branch}


@router.post("/projects/{project_id}/github/pull")
async def github_pull(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    base = project_path(user["user_id"], project_id)
    branch = payload.get("branch") or git_current_branch(base)
    code, out, err = git_pull(token, base, branch)
    return {"ok": code == 0, "stdout": out, "stderr": err, "branch": branch}


@router.post("/projects/{project_id}/github/pr")
async def github_pull_request(project_id: str, payload: dict,
                              user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    full_name = (proj or {}).get("github_full_name") or payload.get("full_name", "")
    if not full_name:
        raise HTTPException(status_code=400, detail="Project not linked to a GitHub repo")
    base = project_path(user["user_id"], project_id)
    head = payload.get("head") or git_current_branch(base)
    base_branch = payload.get("base") or "main"
    title = payload.get("title") or "Sovereign Gauntlet PR"
    body = payload.get("body") or "Opened from Gauntlet DevSpace."
    try:
        pr = await open_pr(token, full_name, head, base_branch, title, body)
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "pr": {"number": pr["number"], "html_url": pr["html_url"], "state": pr["state"]}}
