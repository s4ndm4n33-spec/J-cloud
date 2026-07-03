"""Local git routes — status / commit / log (operates on workspace .git)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends

from deps import get_current_user, project_path

router = APIRouter()


def _git(args: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


@router.get("/projects/{project_id}/git/status")
async def git_status(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    code, out, err = _git(["status", "--porcelain", "-b"], base)
    if code != 0:
        return {"branch": "main", "files": [], "error": err}
    lines = out.strip().splitlines()
    branch = "main"
    files = []
    for ln in lines:
        if ln.startswith("##"):
            branch = ln[3:].split("...")[0].strip() or "main"
        elif ln:
            status = ln[:2]
            name = ln[3:].strip()
            files.append({"status": status.strip(), "path": name})
    return {"branch": branch, "files": files}


@router.post("/projects/{project_id}/git/commit")
async def git_commit(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    msg = payload.get("message") or "shard commit"
    paths = payload.get("paths") or ["."]
    _git(["add", *paths], base)
    code, out, err = _git(["commit", "-m", msg], base)
    return {"ok": code == 0, "stdout": out, "stderr": err}


@router.get("/projects/{project_id}/git/log")
async def git_log(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    code, out, _ = _git(["log", "--oneline", "-n", "30"], base)
    if code != 0:
        return {"commits": []}
    commits = []
    for ln in out.splitlines():
        parts = ln.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})
    return {"commits": commits}
