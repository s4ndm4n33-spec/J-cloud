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
    if r.status_code == 200:
        return r.json()
    # Surface a clean, human-readable error
    try:
        body = r.json()
        msg = body.get("message", r.text[:200])
    except Exception:  # noqa: BLE001
        msg = r.text[:200]
    if r.status_code == 401:
        raise GitHubError(f"GitHub rejected this token (401 Bad credentials). Token is invalid, expired, or lacks 'read:user' scope. Detail: {msg}")
    if r.status_code == 403:
        raise GitHubError(f"GitHub denied access (403). Token may lack scopes or be SSO-restricted. Detail: {msg}")
    raise GitHubError(f"GitHub /user returned {r.status_code}: {msg}")


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

import shutil as _shutil


def _git_binary_available() -> bool:
    return _shutil.which("git") is not None


def _run(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    if args and args[0] == "git" and not _git_binary_available():
        return 127, "", (
            "git binary not found in this environment. "
            "Clone is using the pure-Python dulwich fallback; "
            "other git ops (status/log/push) require the git CLI — "
            "ask the platform to install `git` in the production container."
        )
    try:
        r = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", f"binary not found: {e}"
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


def _https_with_token(clone_url: str, token: str) -> str:
    """Inject token into the https URL for authenticated clone/push.
    Returns the URL unchanged when token is empty (anonymous public clone).
    """
    if not token:
        return clone_url
    if clone_url.startswith("https://"):
        return clone_url.replace("https://", f"https://x-access-token:{token}@", 1)
    return clone_url


def _clone_via_dulwich(clone_url: str, token: str, dest: Path) -> tuple[int, str, str]:
    """Pure-Python clone — works without the git binary."""
    try:
        from dulwich import porcelain
    except ImportError as e:
        return 1, "", f"dulwich not available: {e}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = _https_with_token(clone_url, token)
    try:
        porcelain.clone(url, str(dest), depth=50)
    except Exception as e:  # noqa: BLE001 — dulwich raises a variety of errors
        return 1, "", f"dulwich clone failed: {e}"
    # Strip token from the persisted remote
    try:
        porcelain.remote_set_url(str(dest), "origin", clone_url)
    except Exception:
        pass
    return 0, f"cloned via dulwich into {dest.name}", ""


def git_clone(token: str, clone_url: str, dest: Path) -> tuple[int, str, str]:
    # Prefer the git binary (faster, full features). Fall back to dulwich when
    # the binary is missing (typical in slim production containers).
    if _git_binary_available():
        url = _https_with_token(clone_url, token)
        dest.parent.mkdir(parents=True, exist_ok=True)
        code, out, err = _run(
            ["git", "clone", "--depth", "50", url, str(dest)],
            dest.parent, timeout=180,
        )
        if code == 0:
            _run(["git", "remote", "set-url", "origin", clone_url], dest)
        return code, out, err
    # Production fallback
    return _clone_via_dulwich(clone_url, token, dest)


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
