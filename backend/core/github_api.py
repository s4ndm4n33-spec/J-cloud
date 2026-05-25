"""GitHub REST API client (PAT-first; OAuth follow-up)."""
from __future__ import annotations

import asyncio
import base64
import shlex
import subprocess
from pathlib import Path
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def whoami(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{GITHUB_API}/user", headers=_headers(token))
    if r.status_code != 200:
        raise GitHubError(f"whoami failed: {r.status_code} {r.text[:200]}")
    return r.json()


async def list_repos(token: str, page: int = 1) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{GITHUB_API}/user/repos",
            headers=_headers(token),
            params={"per_page": 50, "page": page, "sort": "updated", "affiliation": "owner,collaborator"},
        )
    if r.status_code != 200:
        raise GitHubError(f"list_repos failed: {r.status_code}")
    return [
        {
            "full_name": x["full_name"],
            "name": x["name"],
            "private": x["private"],
            "default_branch": x.get("default_branch", "main"),
            "description": x.get("description"),
            "updated_at": x.get("updated_at"),
            "html_url": x["html_url"],
            "clone_url": x["clone_url"],
        }
        for x in r.json()
    ]


async def create_repo(token: str, name: str, private: bool, description: str = "") -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{GITHUB_API}/user/repos",
            headers=_headers(token),
            json={"name": name, "private": private, "description": description, "auto_init": False},
        )
    if r.status_code not in (200, 201):
        raise GitHubError(f"create_repo failed: {r.status_code} {r.text[:300]}")
    return r.json()


async def open_pr(token: str, full_name: str, head: str, base: str,
                  title: str, body: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{GITHUB_API}/repos/{full_name}/pulls",
            headers=_headers(token),
            json={"head": head, "base": base, "title": title, "body": body},
        )
    if r.status_code not in (200, 201):
        raise GitHubError(f"open_pr failed: {r.status_code} {r.text[:300]}")
    return r.json()


# ---------- git CLI helpers (workspaces are already git-initialized) ----------


def _run(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


def _https_with_token(clone_url: str, token: str) -> str:
    """Inject token into the https URL: https://x-access-token:<token>@github.com/...
    """
    if clone_url.startswith("https://"):
        return clone_url.replace("https://", f"https://x-access-token:{token}@", 1)
    return clone_url


def git_clone(token: str, clone_url: str, dest: Path) -> tuple[int, str, str]:
    url = _https_with_token(clone_url, token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = _run(["git", "clone", "--depth", "50", url, str(dest)], dest.parent, timeout=180)
    # Rewrite origin to non-token URL so it isn't persisted on disk
    if code == 0:
        _run(["git", "remote", "set-url", "origin", clone_url], dest)
    return code, out, err


def git_set_remote(repo_path: Path, clone_url: str) -> tuple[int, str, str]:
    # remove existing
    _run(["git", "remote", "remove", "origin"], repo_path)
    return _run(["git", "remote", "add", "origin", clone_url], repo_path)


def git_push(token: str, repo_path: Path, branch: str = "main",
             set_upstream: bool = True) -> tuple[int, str, str]:
    code, out, err = _run(["git", "remote", "get-url", "origin"], repo_path)
    if code != 0:
        return code, out, err
    origin = out.strip()
    tokened = _https_with_token(origin, token)
    args = ["git", "push", tokened]
    if set_upstream:
        args += ["-u", branch]
    else:
        args += [branch]
    return _run(args, repo_path, timeout=120)


def git_pull(token: str, repo_path: Path, branch: str = "main") -> tuple[int, str, str]:
    code, out, _ = _run(["git", "remote", "get-url", "origin"], repo_path)
    if code != 0:
        return code, "", ""
    origin = out.strip()
    tokened = _https_with_token(origin, token)
    return _run(["git", "pull", tokened, branch], repo_path, timeout=120)


def git_current_branch(repo_path: Path) -> str:
    code, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return (out.strip() or "main") if code == 0 else "main"
