"""Gauntlet DevSpace - Sovereign Shards cloud IDE backend.

FastAPI server providing:
- Emergent Google OAuth (sessions)
- Project workspace + file CRUD
- Integrated terminal exec (with destructive code hard-block + password override)
- AI Coworker: Gemini chat / GPT-5.2 refine / Claude Sonnet 4.5 governance
- Five Masters AST evaluation
- Git integration
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from core.agent_prompt import AGENT_PROMPT
from core.destructive import scan as destructive_scan, scan_command
from core.fivemasters import evaluate as fm_evaluate
from core.github_api import (
    GitHubError, create_repo, git_clone, git_current_branch, git_pull, git_push,
    git_set_remote, list_repos, open_pr, whoami,
)
from core.keyvault import SUPPORTED_PROVIDERS, decrypt_key, encrypt_key, mask
from core.migration_log import (
    ensure_log, log_audit, log_manual, log_session_start, log_tool_event, read_log,
)
from core.persistence import (
    associative_recall, associative_record, chronos_append, chronos_read,
    heuristic_get, heuristic_update, render_signature,
)
from core.persona import CHAT_PROMPT, REFINE_PROMPT, GOVERNANCE_PROMPT
from core.pty_session import PtySession
from core.scoring import audit_project
from core.tools import ToolContext, execute_tool, parse_tool_calls, strip_tool_calls

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
WORKSPACE_ROOT = Path(os.environ["WORKSPACE_ROOT"])
OVERRIDE_PASSWORD = os.environ["OVERRIDE_PASSWORD"]
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("gauntlet")

app = FastAPI(title="Gauntlet DevSpace API")
api = APIRouter(prefix="/api")


# ---------- AUTH ----------

EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


async def get_current_user(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = sess["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@api.post("/auth/session")
async def auth_session(payload: dict, response: Response):
    """Exchange Emergent session_id for a session_token cookie."""
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Emergent auth failed: {r.text}")
    data = r.json()

    email = data["email"]
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name", email.split("@")[0]),
            "picture": data.get("picture", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(dict(user))
        user.pop("_id", None)
    else:
        await db.users.update_one(
            {"email": email},
            {"$set": {"name": data.get("name", user["name"]),
                      "picture": data.get("picture", user.get("picture", ""))}},
        )

    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    response.set_cookie(
        key="session_token", value=session_token, path="/",
        max_age=7 * 24 * 3600, httponly=True, secure=True, samesite="none",
    )
    # Also return token in body so mobile (where 3rd-party cookies are blocked)
    # can store it in localStorage and send via Authorization: Bearer header.
    return {"user": user, "session_token": session_token}


@api.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return user


@api.post("/auth/logout")
async def auth_logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ---------- WORKSPACE & PROJECTS ----------

def user_root(user_id: str) -> Path:
    p = WORKSPACE_ROOT / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def project_path(user_id: str, project_id: str) -> Path:
    p = user_root(user_id) / project_id
    if not p.exists():
        # Self-heal: if DB references it but disk is gone, re-seed.
        log.warning(f"Re-seeding missing project dir {p}")
        seed_project(p)
    return p


def safe_join(base: Path, rel: str) -> Path:
    """Prevent path traversal."""
    rel = rel.lstrip("/")
    candidate = (base / rel).resolve()
    if base.resolve() not in candidate.parents and candidate != base.resolve():
        raise HTTPException(status_code=400, detail="Path escapes project root")
    return candidate


SAMPLE_FILES = {
    "README.md": (
        "# Welcome to Gauntlet DevSpace\n\n"
        "> DETERMINISTIC. AUTONOMOUS. SUBSTRATE.\n\n"
        "This is your Sovereign Shards cloud workspace. Try:\n\n"
        "- Open `main.py` and press **Cmd+K** to invoke J for inline refinement.\n"
        "- Hit the **Gauntlet** tab in the right panel for a Five Masters review.\n"
        "- Toggle **Live Preview** to see HTML in `index.html` render.\n\n"
        "If it can't prove integrity, it halts.\n"
    ),
    "main.py": (
        "def greet(name: str) -> str:\n"
        "    \"\"\"Return a greeting. Type-hinted, PEP 8.\"\"\"\n"
        "    return f\"Hello, {name}\"\n\n\n"
        "def slow_lookup(items):\n"
        "    # Intentionally wasteful for the Gauntlet demo.\n"
        "    result = []\n"
        "    for i in range(len(items)):\n"
        "        result.append(items[i].upper())\n"
        "    return result\n\n\n"
        "if __name__ == \"__main__\":\n"
        "    print(greet(\"sovereign\"))\n"
        "    print(slow_lookup([\"a\", \"b\", \"c\"]))\n"
    ),
    "index.html": (
        "<!doctype html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n"
        "  <title>Sovereign Shard</title>\n"
        "  <style>\n"
        "    body{margin:0;background:#050709;color:#E7ECF5;"
        "font-family:'JetBrains Mono',monospace;display:flex;"
        "align-items:center;justify-content:center;height:100vh}\n"
        "    h1{color:#00D9FF;letter-spacing:.2em;font-size:2.5rem}\n"
        "    p{color:#7D8597}\n"
        "  </style>\n"
        "</head>\n<body>\n"
        "  <div><h1>SOVEREIGN SHARDS</h1>"
        "<p>// deterministic. autonomous. substrate.</p></div>\n"
        "</body>\n</html>\n"
    ),
    ".gitignore": "node_modules/\n__pycache__/\n.venv/\n*.pyc\n",
    ".gauntletignore": (
        "# Patterns J's Gauntlet auditor will ignore.\n"
        "# One glob per line. Same syntax as .gitignore (subset).\n"
        "node_modules/\n"
        "dist/\n"
        "build/\n"
        ".venv/\n"
        "__pycache__/\n"
        "*.min.js\n"
        "*.lock\n"
    ),
}


def seed_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, content in SAMPLE_FILES.items():
        (path / name).write_text(content)
    # init git
    try:
        subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "j@sovereign.shards"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "J"], cwd=path, check=True)
        subprocess.run(["git", "add", "."], cwd=path, check=True, timeout=10)
        subprocess.run(["git", "commit", "-q", "-m", "Initial shard"], cwd=path, check=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning(f"git init failed: {e}")


@api.get("/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    docs = await db.projects.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(200)
    return docs


@api.post("/projects")
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


@api.get("/projects/{project_id}/tree")
async def project_tree(project_id: str, user: dict = Depends(get_current_user)):
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


class FileReadResp(BaseModel):
    path: str
    content: str
    language: str


def detect_language(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "py": "python", "js": "javascript", "jsx": "javascript",
        "ts": "typescript", "tsx": "typescript", "json": "json",
        "md": "markdown", "html": "html", "css": "css", "yml": "yaml",
        "yaml": "yaml", "sh": "shell", "rs": "rust", "go": "go",
        "java": "java", "c": "c", "cpp": "cpp", "rb": "ruby", "php": "php",
        "sql": "sql", "toml": "toml", "ini": "ini",
    }.get(ext, "plaintext")


@api.get("/projects/{project_id}/file")
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


@api.post("/projects/{project_id}/file")
async def write_file(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    path = payload.get("path", "")
    content = payload.get("content", "")
    target = safe_join(base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "bytes": len(content)}


@api.delete("/projects/{project_id}/file")
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


# ---------- FIVE MASTERS GAUNTLET ----------

@api.post("/gauntlet/evaluate")
async def gauntlet_evaluate(payload: dict, user: dict = Depends(get_current_user)):
    code = payload.get("code", "")
    language = payload.get("language", "python")
    report = fm_evaluate(code, language)
    return report.to_dict()


# ---------- DESTRUCTIVE-CODE INTERLOCK ----------

@api.post("/governance/scan")
async def governance_scan(payload: dict, user: dict = Depends(get_current_user)):
    code = payload.get("code") or payload.get("command") or ""
    matches = destructive_scan(code)
    return {
        "blocked": any(m.severity == "critical" for m in matches),
        "warn": any(m.severity == "high" for m in matches),
        "matches": [
            {"pattern": m.pattern, "line": m.line, "snippet": m.snippet,
             "severity": m.severity, "reason": m.reason} for m in matches
        ],
    }


@api.post("/governance/override")
async def governance_override(payload: dict, user: dict = Depends(get_current_user)):
    """Verify password to permit a destructive op."""
    if payload.get("password", "") != OVERRIDE_PASSWORD:
        await db.override_log.insert_one({
            "user_id": user["user_id"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "outcome": "rejected",
            "intent": payload.get("intent", ""),
        })
        raise HTTPException(status_code=403, detail="Override password incorrect")
    token = f"ovr_{uuid.uuid4().hex[:20]}"
    await db.overrides.insert_one({
        "token": token,
        "user_id": user["user_id"],
        "intent": payload.get("intent", ""),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    })
    await db.override_log.insert_one({
        "user_id": user["user_id"],
        "ts": datetime.now(timezone.utc).isoformat(),
        "outcome": "granted",
        "intent": payload.get("intent", ""),
    })
    return {"override_token": token, "expires_in": 120}


async def consume_override(user_id: str, token: Optional[str]) -> bool:
    if not token:
        return False
    doc = await db.overrides.find_one({"token": token, "user_id": user_id}, {"_id": 0})
    if not doc:
        return False
    exp = doc["expires_at"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return False
    await db.overrides.delete_one({"token": token})
    return True


# ---------- TERMINAL ----------

BLOCKED_COMMANDS_CRITICAL = ("rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "shutil.rmtree('/')")


@api.post("/terminal/exec")
async def terminal_exec(payload: dict, user: dict = Depends(get_current_user)):
    project_id = payload.get("project_id", "")
    cmd = payload.get("command", "").strip()
    override_token = payload.get("override_token")
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    base = project_path(user["user_id"], project_id)

    matches = scan_command(cmd)
    has_critical = any(m.severity == "critical" for m in matches)
    has_high = any(m.severity == "high" for m in matches)

    if has_critical or has_high:
        allowed = await consume_override(user["user_id"], override_token)
        if not allowed:
            return JSONResponse(
                status_code=423,
                content={
                    "blocked": True,
                    "severity": "critical" if has_critical else "high",
                    "matches": [
                        {"pattern": m.pattern, "reason": m.reason,
                         "snippet": m.snippet, "line": m.line, "severity": m.severity}
                        for m in matches
                    ],
                    "message": "INTEGRITY HALT - destructive command detected. Password override required.",
                },
            )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        return {"stdout": "", "stderr": "Timeout (300s) — for long-running daemons use the interactive terminal.", "exit_code": 124}
    except OSError as e:
        return {"stdout": "", "stderr": f"Exec error: {e}", "exit_code": 1}


# ---------- INTERACTIVE PTY-BACKED TERMINAL (WebSocket) ----------

_MAX_SHELLS_PER_USER = 5
_user_shell_count: dict[str, int] = {}


async def _user_from_token(token: Optional[str], cookie_token: Optional[str]) -> Optional[dict]:
    """Resolve a user from either ?token=... or session_token cookie."""
    raw = token or cookie_token
    if not raw:
        return None
    sess = await db.user_sessions.find_one(
        {"session_token": raw, "expires_at": {"$gt": datetime.now(timezone.utc).isoformat()}},
        {"_id": 0},
    )
    if not sess:
        return None
    return await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})


@app.websocket("/api/terminal/ws")
async def terminal_ws(
    websocket: WebSocket,
    project_id: str = Query(...),
    token: Optional[str] = Query(default=None),
):
    cookie_token = websocket.cookies.get("session_token")
    user = await _user_from_token(token, cookie_token)
    if not user:
        await websocket.close(code=4401)
        return

    uid = user["user_id"]
    if _user_shell_count.get(uid, 0) >= _MAX_SHELLS_PER_USER:
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "msg": f"too many open shells ({_MAX_SHELLS_PER_USER}/user) — close an existing terminal first.",
        })
        await websocket.close(code=4429)
        return

    base = project_path(user["user_id"], project_id)
    await websocket.accept()
    _user_shell_count[uid] = _user_shell_count.get(uid, 0) + 1

    session = PtySession(cwd=str(base))
    try:
        await session.start()
    except OSError as e:
        await websocket.send_json({"type": "error", "msg": f"shell start failed: {e}"})
        await websocket.close()
        return

    async def pump_pty_to_ws():
        while not session.closed:
            data = await session.read()
            if not data:
                break
            try:
                await websocket.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError):
                break

    async def pump_ws_to_pty():
        try:
            while not session.closed:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "text" in msg and msg["text"] is not None:
                    # control frames: resize, ping
                    try:
                        ctrl = json.loads(msg["text"])
                    except (ValueError, TypeError):
                        session.write(msg["text"].encode("utf-8"))
                        continue
                    if ctrl.get("type") == "resize":
                        session.set_size(int(ctrl.get("cols", 80)),
                                         int(ctrl.get("rows", 24)))
                    elif ctrl.get("type") == "input":
                        session.write(str(ctrl.get("data", "")).encode("utf-8"))
                elif "bytes" in msg and msg["bytes"] is not None:
                    session.write(msg["bytes"])
        except WebSocketDisconnect:
            pass

    pty_task = asyncio.create_task(pump_pty_to_ws())
    ws_task = asyncio.create_task(pump_ws_to_pty())
    try:
        # As soon as EITHER pump exits (client disconnect or PTY EOF), tear down
        # the other one so the shell counter slot is released immediately.
        done, pending = await asyncio.wait(
            {pty_task, ws_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        # Closing the session causes pump_pty_to_ws's queue.get() to return b""
        # and cancels its loop. Cancelling pending also closes the WS task cleanly.
        session.close()
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, WebSocketDisconnect, OSError):
                pass
    finally:
        session.close()
        _user_shell_count[uid] = max(0, _user_shell_count.get(uid, 1) - 1)
        try:
            await websocket.close()
        except RuntimeError:
            pass


# ---------- GIT ----------

def _git(args: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


@api.get("/projects/{project_id}/git/status")
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


@api.post("/projects/{project_id}/git/commit")
async def git_commit(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    msg = payload.get("message") or "shard commit"
    paths = payload.get("paths") or ["."]
    _git(["add", *paths], base)
    code, out, err = _git(["commit", "-m", msg], base)
    return {"ok": code == 0, "stdout": out, "stderr": err}


@api.get("/projects/{project_id}/git/log")
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


# ---------- AI COWORKER ----------

def _build_context_block(payload: dict) -> str:
    parts = []
    if payload.get("file_path"):
        parts.append(f"Open file: {payload['file_path']}")
    if payload.get("file_content"):
        lang = payload.get("language", "")
        parts.append(f"```{lang}\n{payload['file_content']}\n```")
    if payload.get("tree_summary"):
        parts.append("Project tree (truncated):\n" + payload["tree_summary"])
    return "\n\n".join(parts)


async def _resolve_byok(user_id: str, provider: str) -> Optional[Any]:
    """Return BYO config for provider.

    Cloud providers (openai/anthropic/gemini) → returns the decrypted api_key string.
    Ollama / local OpenAI-compatible server → returns dict {base_url, default_model}.
    Returns None when not configured.
    """
    doc = await db.user_provider_keys.find_one(
        {"user_id": user_id, "provider": provider}, {"_id": 0}
    )
    if not doc:
        return None
    if provider == "ollama":
        base_url = doc.get("base_url") or ""
        default_model = doc.get("default_model") or ""
        if not base_url or not default_model:
            return None
        return {"base_url": base_url, "default_model": default_model}
    if doc.get("ciphertext"):
        try:
            return decrypt_key(doc["ciphertext"])
        except (ValueError, TypeError):
            log.warning(f"BYOK decrypt failed for {user_id}/{provider}")
    return None


# Task chains: Universal first, then BYO of preferred provider, then BYO of others.
# Each step: (source, provider, model). source = "universal" or "byok".
# Ollama model "user-default" means: use whatever default_model the user saved.
TASK_CHAINS: dict[str, list[tuple[str, str, str]]] = {
    "chat": [
        ("universal", "gemini",    "gemini-3-flash-preview"),
        ("byok",      "gemini",    "gemini-3-flash-preview"),
        ("byok",      "openai",    "gpt-5.4-mini"),
        ("byok",      "anthropic", "claude-haiku-4-5-20251001"),
        ("byok",      "ollama",    "user-default"),
    ],
    "refine": [
        ("universal", "openai",    "gpt-5.2"),
        ("byok",      "openai",    "gpt-5.2"),
        ("byok",      "anthropic", "claude-sonnet-4-5-20250929"),
        ("byok",      "gemini",    "gemini-3-flash-preview"),
        ("byok",      "ollama",    "user-default"),
    ],
    "governance": [
        ("universal", "anthropic", "claude-sonnet-4-5-20250929"),
        ("byok",      "anthropic", "claude-sonnet-4-5-20250929"),
        ("byok",      "openai",    "gpt-5.4"),
        ("byok",      "gemini",    "gemini-3.1-pro-preview"),
        ("byok",      "ollama",    "user-default"),
    ],
}


async def _call_ollama(base_url: str, model: str, system: str, user_text: str) -> str:
    """Call an OpenAI-compatible local server (Ollama, llama.cpp, vLLM)."""
    from openai import AsyncOpenAI
    base = base_url.rstrip("/")
    # Ollama and llama.cpp both expose /v1 OpenAI-compat endpoints.
    if not base.endswith("/v1"):
        base = base + "/v1"
    client_ai = AsyncOpenAI(api_key="local", base_url=base, timeout=60.0)
    resp = await client_ai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text},
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content or ""


async def _single_call(api_key_or_cfg: Any, provider: str, model: str,
                       system: str, user_text: str, session_id: str) -> str:
    if provider == "ollama":
        cfg = api_key_or_cfg if isinstance(api_key_or_cfg, dict) else {}
        chosen_model = model if model != "user-default" else cfg.get("default_model", "")
        if not chosen_model:
            raise RuntimeError("Ollama default model not configured")
        return await _call_ollama(cfg["base_url"], chosen_model, system, user_text)

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=api_key_or_cfg,
        session_id=session_id,
        system_message=system,
    ).with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=user_text))
    return resp if isinstance(resp, str) else str(resp)


async def _chain_call(user_id: str, task: str, system: str, user_text: str,
                      session_id: str, max_passes: int = 2
                      ) -> tuple[str, dict]:
    """Run the LLM call through the failover chain. Returns (reply, metadata).

    Metadata: {success: bool, step_used: {...}, attempts: [...], total_ms: int}.

    When the user has private_mode=True, the chain is filtered to ollama-only
    steps so neither the Universal Key nor any cloud BYOK is ever touched.
    """
    import time as _time
    chain = TASK_CHAINS.get(task, TASK_CHAINS["chat"])

    # Apply Private Mode filter
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0, "private_mode": 1})
    private_mode = bool(user_doc and user_doc.get("private_mode"))
    if private_mode:
        chain = [s for s in chain if s[1] == "ollama"]

    attempts: list[dict] = []
    chain_started = _time.perf_counter()

    for pass_idx in range(max_passes):
        for source, provider, model in chain:
            if source == "universal":
                api_key = EMERGENT_LLM_KEY
            else:
                api_key = await _resolve_byok(user_id, provider)
                if not api_key:
                    attempts.append({"pass": pass_idx, "source": source,
                                     "provider": provider, "model": model,
                                     "status": "skipped", "reason": "byok-missing",
                                     "ms": 0})
                    continue
            t0 = _time.perf_counter()
            try:
                reply = await _single_call(
                    api_key, provider, model, system, user_text,
                    f"{session_id}-{source}-{provider}",
                )
                ms = int((_time.perf_counter() - t0) * 1000)
                attempts.append({"pass": pass_idx, "source": source,
                                 "provider": provider, "model": model,
                                 "status": "ok", "ms": ms})
                meta = {
                    "success": True,
                    "step_used": {"source": source, "provider": provider, "model": model},
                    "attempts": attempts,
                    "total_ms": int((_time.perf_counter() - chain_started) * 1000),
                    "task": task,
                }
                await _record_telemetry(user_id, meta)
                return reply, meta
            except Exception as e:  # noqa: BLE001
                ms = int((_time.perf_counter() - t0) * 1000)
                short = str(e)[:280]
                log.warning(f"chain[{task}] {source}/{provider}/{model} failed in {ms}ms: {short}")
                attempts.append({"pass": pass_idx, "source": source,
                                 "provider": provider, "model": model,
                                 "status": "error", "reason": short, "ms": ms})
                continue
    meta = {
        "success": False, "step_used": None, "attempts": attempts,
        "total_ms": int((_time.perf_counter() - chain_started) * 1000),
        "task": task,
    }
    await _record_telemetry(user_id, meta)
    return "", meta


async def _record_telemetry(user_id: str, meta: dict) -> None:
    """Persist a chain-call event for the telemetry strip."""
    fallbacks = max(0, len([a for a in meta.get("attempts", [])
                            if a.get("status") in ("error", "skipped")]))
    doc = {
        "user_id": user_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": meta.get("task"),
        "success": meta.get("success"),
        "step_used": meta.get("step_used"),
        "total_ms": meta.get("total_ms", 0),
        "fallbacks": fallbacks,
        "attempts_count": len(meta.get("attempts", [])),
    }
    try:
        await db.llm_telemetry.insert_one(doc)
    except Exception as e:  # noqa: BLE001
        log.warning(f"telemetry insert failed: {e}")


# ---------- SETTINGS / BYOK ----------

OLLAMA_PRESETS = {
    "ollama":     "http://localhost:11434",
    "llama-cpp":  "http://localhost:8080",
}


def _valid_local_url(url: str) -> bool:
    """Accept http(s)://host[:port] — keep it permissive but reject obvious junk."""
    if not isinstance(url, str):
        return False
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    if " " in u or len(u) > 256:
        return False
    return True


@api.get("/settings/keys")
async def list_keys(user: dict = Depends(get_current_user)):
    docs = await db.user_provider_keys.find(
        {"user_id": user["user_id"]}, {"_id": 0, "ciphertext": 0}
    ).to_list(20)
    have = {d["provider"]: d for d in docs}
    out = []
    for prov in SUPPORTED_PROVIDERS:
        if prov in have:
            d = have[prov]
            entry = {
                "provider": prov,
                "configured": True,
                "masked": d.get("masked", ""),
                "updated_at": d.get("updated_at"),
            }
            if prov == "ollama":
                entry["base_url"] = d.get("base_url", "")
                entry["default_model"] = d.get("default_model", "")
            out.append(entry)
        else:
            entry = {"provider": prov, "configured": False, "masked": "", "updated_at": None}
            if prov == "ollama":
                entry["base_url"] = ""
                entry["default_model"] = ""
            out.append(entry)
    return {
        "providers": out,
        "universal_key_available": bool(EMERGENT_LLM_KEY),
        "ollama_presets": OLLAMA_PRESETS,
    }


@api.put("/settings/keys")
async def set_key(payload: dict, user: dict = Depends(get_current_user)):
    provider = payload.get("provider", "")
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    if provider == "ollama":
        base_url = (payload.get("base_url") or "").strip()
        default_model = (payload.get("default_model") or "").strip()
        if not _valid_local_url(base_url):
            raise HTTPException(status_code=400, detail="Invalid base URL (must start with http:// or https://)")
        if not default_model:
            raise HTTPException(status_code=400, detail="Default model is required (e.g., llama3.1)")
        doc = {
            "user_id": user["user_id"],
            "provider": provider,
            "base_url": base_url,
            "default_model": default_model,
            "masked": f"{base_url} · {default_model}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.user_provider_keys.update_one(
            {"user_id": user["user_id"], "provider": provider},
            {"$set": doc},
            upsert=True,
        )
        return {"ok": True, "provider": provider, "masked": doc["masked"]}

    api_key = (payload.get("api_key") or "").strip()
    if not api_key or len(api_key) < 12:
        raise HTTPException(status_code=400, detail="Invalid API key")
    doc = {
        "user_id": user["user_id"],
        "provider": provider,
        "ciphertext": encrypt_key(api_key),
        "masked": mask(api_key),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.user_provider_keys.update_one(
        {"user_id": user["user_id"], "provider": provider},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "provider": provider, "masked": doc["masked"]}


@api.delete("/settings/keys/{provider}")
async def delete_key(provider: str, user: dict = Depends(get_current_user)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    await db.user_provider_keys.delete_one(
        {"user_id": user["user_id"], "provider": provider}
    )
    return {"ok": True, "provider": provider}


@api.post("/settings/keys/ollama/test")
async def test_ollama(payload: dict, user: dict = Depends(get_current_user)):
    """Smoke-test the user's Ollama / llama.cpp endpoint. Tries /api/tags then falls
    back to OpenAI-compat /v1/models. Returns models list on success.
    """
    base_url = (payload.get("base_url") or "").strip()
    if not _valid_local_url(base_url):
        raise HTTPException(status_code=400, detail="Invalid base URL")
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=8.0) as http:
        # Try Ollama native first
        try:
            r = await http.get(f"{base}/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return {"ok": True, "backend": "ollama", "models": models}
        except (httpx.HTTPError, ValueError):
            pass
        # Fall back to OpenAI-compat
        try:
            r = await http.get(f"{base}/v1/models")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                return {"ok": True, "backend": "openai-compat", "models": models}
        except (httpx.HTTPError, ValueError) as e:
            return {"ok": False, "error": f"Unreachable: {e}"}
    return {"ok": False, "error": "Endpoint did not respond to /api/tags or /v1/models"}


# ---------- TUTORIAL STATE ----------

@api.get("/me/tutorial")
async def tutorial_state(user: dict = Depends(get_current_user)):
    completed = bool(user.get("tutorial_completed", False))
    return {"completed": completed}


@api.post("/me/tutorial")
async def set_tutorial_state(payload: dict, user: dict = Depends(get_current_user)):
    completed = bool(payload.get("completed", True))
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"tutorial_completed": completed,
                  "tutorial_updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "completed": completed}


@api.get("/me/private-mode")
async def get_private_mode(user: dict = Depends(get_current_user)):
    enabled = bool(user.get("private_mode", False))
    ollama_cfg = await _resolve_byok(user["user_id"], "ollama")
    return {"enabled": enabled, "ollama_ready": bool(ollama_cfg)}


@api.post("/me/private-mode")
async def set_private_mode(payload: dict, user: dict = Depends(get_current_user)):
    enabled = bool(payload.get("enabled", False))
    if enabled:
        ollama_cfg = await _resolve_byok(user["user_id"], "ollama")
        if not ollama_cfg:
            raise HTTPException(
                status_code=400,
                detail="Link a local server (Ollama / llama.cpp) in Settings before enabling Private Mode.",
            )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"private_mode": enabled,
                  "private_mode_updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "enabled": enabled}


@api.post("/ai/chat")
async def ai_chat(payload: dict, user: dict = Depends(get_current_user)):
    """Gemini-first chat with BYOK failover chain."""
    conversation_id = payload.get("conversation_id") or f"conv_{uuid.uuid4().hex[:10]}"
    message = payload.get("message", "")
    ctx = _build_context_block(payload)
    user_text = f"{ctx}\n\n[USER]\n{message}" if ctx else message

    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "user",
        "content": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    reply, meta = await _chain_call(
        user["user_id"], "chat", CHAT_PROMPT, user_text,
        f"{user['user_id']}-{conversation_id}",
    )
    if not meta["success"]:
        reply = (
            "// J:OFFLINE — entire LLM failover chain exhausted.\n"
            "// Add a provider key in Settings (gear icon) or top up Universal Key balance.\n"
            f"// last attempts: {len(meta['attempts'])}"
        )

    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
    })
    return {"conversation_id": conversation_id, "reply": reply, "meta": meta}


@api.get("/ai/chat/history")
async def ai_chat_history(conversation_id: str, user: dict = Depends(get_current_user)):
    docs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(500)
    return {"messages": docs}


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if model ignored instructions."""
    t = text.strip()
    if t.startswith("```"):
        # drop first line
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.rstrip() + "\n"


@api.post("/ai/refine")
async def ai_refine(payload: dict, user: dict = Depends(get_current_user)):
    """GPT-5.2 surgical refine. Returns refined code + auto-Gauntlet verdict."""
    code = payload.get("code", "")
    instruction = payload.get("instruction", "")
    language = payload.get("language", "python")

    user_text = (
        f"[LANGUAGE]\n{language}\n\n"
        f"[INSTRUCTION]\n{instruction}\n\n"
        f"[ORIGINAL CODE]\n{code}\n\n"
        f"Return ONLY the refined code. No fences. No prose."
    )
    reply, meta = await _chain_call(
        user["user_id"], "refine", REFINE_PROMPT, user_text,
        f"{user['user_id']}-refine-{uuid.uuid4().hex[:6]}",
    )
    if not meta["success"]:
        raise HTTPException(status_code=502, detail={
            "message": "LLM failover chain exhausted",
            "attempts": meta["attempts"],
        })
    refined = _strip_code_fences(reply)

    # Run AST gauntlet on the refined output
    ast_report = fm_evaluate(refined, language).to_dict()

    # Destructive scan on output (don't auto-block - surface to UI)
    danger = destructive_scan(refined)
    return {
        "refined": refined,
        "ast_report": ast_report,
        "destructive": [
            {"pattern": m.pattern, "line": m.line, "reason": m.reason,
             "severity": m.severity, "snippet": m.snippet} for m in danger
        ],
        "meta": meta,
    }


@api.post("/ai/governance")
async def ai_governance(payload: dict, user: dict = Depends(get_current_user)):
    """Claude Sonnet 4.5 final governance verdict. Strict JSON."""
    code = payload.get("code", "")
    language = payload.get("language", "python")
    ast_report = fm_evaluate(code, language).to_dict()

    user_text = (
        f"[LANGUAGE]\n{language}\n\n"
        f"[CODE]\n```{language}\n{code}\n```\n\n"
        f"[DETERMINISTIC AST REPORT]\n{json.dumps(ast_report, indent=2)}\n\n"
        f"Return strict JSON only as specified."
    )
    raw, meta = await _chain_call(
        user["user_id"], "governance", GOVERNANCE_PROMPT, user_text,
        f"{user['user_id']}-gov-{uuid.uuid4().hex[:6]}",
    )
    if not meta["success"]:
        return {
            "ast_report": ast_report,
            "llm_verdict": {
                "verdict": "PASS" if ast_report["score"] == 5 else "FAIL",
                "summary": "AST-only fallback (LLM chain exhausted).",
                "masters": ast_report["masters"],
                "fixes": [iss["message"] for iss in ast_report["issues"][:5]],
            },
            "meta": meta,
        }

    # Pull JSON out of the response
    m = re.search(r"\{[\s\S]*\}", raw)
    parsed: dict[str, Any]
    if m:
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            parsed = {"verdict": "FAIL", "summary": "Malformed governance JSON",
                      "masters": ast_report["masters"], "fixes": []}
    else:
        parsed = {"verdict": "FAIL", "summary": raw[:200],
                  "masters": ast_report["masters"], "fixes": []}

    return {"ast_report": ast_report, "llm_verdict": parsed, "meta": meta}


# ---------- GITHUB ----------


async def _resolve_github_token(user_id: str) -> Optional[str]:
    doc = await db.user_github.find_one({"user_id": user_id}, {"_id": 0})
    if doc and doc.get("ciphertext"):
        try:
            return decrypt_key(doc["ciphertext"])
        except (ValueError, TypeError):
            log.warning(f"github token decrypt failed for {user_id}")
    return None


@api.get("/github/auth")
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


@api.post("/github/auth")
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


@api.delete("/github/auth")
async def github_auth_delete(user: dict = Depends(get_current_user)):
    await db.user_github.delete_one({"user_id": user["user_id"]})
    return {"ok": True}


@api.get("/github/repos")
async def github_repos(page: int = 1, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    try:
        repos = await list_repos(token, page=page)
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"repos": repos, "page": page}


@api.post("/github/clone")
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


@api.post("/projects/{project_id}/github/create")
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
    # ensure at least one commit
    subprocess.run(["git", "add", "."], cwd=base, capture_output=True, timeout=10)
    subprocess.run(["git", "commit", "-m", "Initial shard from Gauntlet DevSpace"],
                   cwd=base, capture_output=True, timeout=10)
    # Rename to main if needed
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


@api.post("/projects/{project_id}/github/link")
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


@api.post("/projects/{project_id}/github/push")
async def github_push(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    base = project_path(user["user_id"], project_id)
    branch = payload.get("branch") or git_current_branch(base)
    code, out, err = git_push(token, base, branch, set_upstream=True)
    return {"ok": code == 0, "stdout": out, "stderr": err, "branch": branch}


@api.post("/projects/{project_id}/github/pull")
async def github_pull(project_id: str, payload: dict, user: dict = Depends(get_current_user)):
    token = await _resolve_github_token(user["user_id"])
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected")
    base = project_path(user["user_id"], project_id)
    branch = payload.get("branch") or git_current_branch(base)
    code, out, err = git_pull(token, base, branch)
    return {"ok": code == 0, "stdout": out, "stderr": err, "branch": branch}


@api.post("/projects/{project_id}/github/pr")
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


# ---------- AUDIT (100-point score) ----------


@api.get("/projects/{project_id}/audit")
async def project_audit(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    result = audit_project(base)
    try:
        top = result["recommendations"][0]["title"] if result.get("recommendations") else None
        log_audit(base, signer="SYSTEM", score=result["score"],
                  grade=result["grade"], top_recommendation=top)
    except (OSError, KeyError) as e:
        log.warning(f"audit log write failed: {e}")
    return result


@api.get("/projects/{project_id}/migration_log")
async def get_migration_log(project_id: str, user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    return {"content": read_log(base), "path": ".gauntlet/migration.log.md"}


# ---------- RECURSIVE TEMPORAL PERSISTENCE ----------


@api.get("/projects/{project_id}/chronos")
async def chronos_get(project_id: str, limit: int = 100, event_type: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    return {"entries": chronos_read(base, limit=limit, event_type=event_type)}


@api.post("/projects/{project_id}/chronos")
async def chronos_post(project_id: str, payload: dict,
                       user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    entry = chronos_append(
        base,
        event_type=payload.get("event_type", "decision"),
        file=payload.get("file"),
        action=payload.get("action", ""),
        rationale=payload.get("rationale", ""),
        master=payload.get("master", ""),
        sentiment=payload.get("sentiment", "neutral"),
        actor=payload.get("actor") or (user.get("name") or "USER"),
        extra=payload.get("extra"),
    )
    return {"ok": True, "entry": entry}


@api.get("/memory/signature")
async def memory_signature(user: dict = Depends(get_current_user)):
    return await heuristic_get(db, user["user_id"])


@api.post("/memory/recall")
async def memory_recall(payload: dict, user: dict = Depends(get_current_user)):
    q = payload.get("query", "")
    k = int(payload.get("k", 5))
    project_id = payload.get("project_id")
    if not q:
        return {"hits": []}
    hits = await associative_recall(db, user["user_id"], query=q, k=k, project_id=project_id)
    return {"hits": hits}


@api.post("/projects/{project_id}/migration_log")
async def add_migration_log(project_id: str, payload: dict,
                            user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    entry = log_manual(
        base,
        signer=(payload.get("signer") or user.get("name") or user.get("email") or "USER"),
        title=payload.get("title") or "Untitled milestone",
        problem=payload.get("problem", ""),
        fix=payload.get("fix", ""),
        why=payload.get("why", ""),
        next_step=payload.get("next_step", ""),
        tags=payload.get("tags") or ["manual"],
    )
    return {"ok": True, "entry": entry}


# ---------- UPLOAD / DOWNLOAD ----------


@api.post("/projects/{project_id}/upload")
async def upload_file(project_id: str, path: str = "", file: UploadFile = File(...),
                      user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    rel = path or file.filename or "upload.bin"
    target = safe_join(base, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    target.write_bytes(content)
    return {"ok": True, "path": rel, "bytes": len(content)}


@api.post("/projects/{project_id}/upload_zip")
async def upload_zip(
    project_id: str,
    file: UploadFile = File(...),
    dest: str = "",
    strip_root: bool = True,
    user: dict = Depends(get_current_user),
):
    """Ingest a .zip into the workspace. Path-traversal safe, ignores junk dirs.

    strip_root=True drops the single top-level folder common in GitHub-style zips.
    """
    import io
    import zipfile

    base = project_path(user["user_id"], project_id)
    dest_dir = safe_join(base, dest) if dest else base
    dest_dir.mkdir(parents=True, exist_ok=True)

    SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".DS_Store"}
    MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB cap
    MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB per file

    raw = await file.read()
    if len(raw) > MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail=f"Zip too large (>{MAX_TOTAL_BYTES // (1024*1024)}MB)")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail=f"Invalid zip: {e}") from e

    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        raise HTTPException(status_code=400, detail="Zip is empty")

    # Detect a single top-level folder for stripping
    strip_prefix = ""
    if strip_root:
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        only_tops = {n for n in names if "/" not in n}
        if len(tops) == 1 and not only_tops:
            strip_prefix = next(iter(tops)) + "/"

    total = 0
    written = 0
    skipped = 0
    written_paths: list[str] = []

    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        # Normalize separators
        name = name.replace("\\", "/").lstrip("/")
        if strip_prefix and name.startswith(strip_prefix):
            name = name[len(strip_prefix):]
        if not name:
            continue
        parts = name.split("/")
        if any(p in SKIP_PARTS for p in parts) or any(p.startswith("..") for p in parts):
            skipped += 1
            continue
        if info.file_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Total uncompressed size exceeds 500MB cap")
        try:
            target = safe_join(dest_dir, name)
        except HTTPException:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out, length=64 * 1024)
        written += 1
        if len(written_paths) < 200:
            written_paths.append(name)

    return {
        "ok": True,
        "files_written": written,
        "files_skipped": skipped,
        "total_bytes": total,
        "stripped_prefix": strip_prefix or None,
        "dest": dest or "(root)",
        "sample_paths": written_paths[:50],
    }


@api.post("/projects/{project_id}/upload_folder")
async def upload_folder(
    project_id: str,
    files: list[UploadFile] = File(...),
    paths: str = "",  # JSON-encoded list of relative paths matching `files`
    user: dict = Depends(get_current_user),
):
    """Upload multiple files preserving relative paths (browser folder picker)."""
    base = project_path(user["user_id"], project_id)
    rel_paths: list[str] = []
    if paths:
        try:
            rel_paths = json.loads(paths)
        except json.JSONDecodeError:
            rel_paths = []
    written: list[str] = []
    total_bytes = 0
    for i, f in enumerate(files):
        rel = rel_paths[i] if i < len(rel_paths) and rel_paths[i] else (f.filename or f"upload_{i}.bin")
        rel = rel.replace("\\", "/").lstrip("/")
        if any(p in (".git", "node_modules", "__pycache__") for p in rel.split("/")):
            continue
        try:
            target = safe_join(base, rel)
        except HTTPException:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        target.write_bytes(content)
        total_bytes += len(content)
        written.append(rel)
    return {"ok": True, "files_written": len(written), "total_bytes": total_bytes, "paths": written[:200]}


@api.get("/projects/{project_id}/download")
async def download_file(project_id: str, path: str,
                        user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    target = safe_join(base, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


@api.get("/projects/{project_id}/download_zip")
async def download_zip(project_id: str, path: str = "",
                       user: dict = Depends(get_current_user)):
    """Download a project — or a specific folder inside it — as a .zip.

    `path=""` (default) zips the whole project (legacy behavior).
    `path="src/utils"` zips just that sub-folder. The archive's internal paths
    are rooted at the requested folder name so unzipping reproduces it locally.
    """
    base = project_path(user["user_id"], project_id)
    if path:
        target = safe_join(base, path)
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=404, detail="Folder not found")
        zip_root = target
        zip_name = target.name or project_id
        path_prefix = target.name + "/"
    else:
        zip_root = base
        zip_name = project_id
        path_prefix = ""

    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in zip_root.rglob("*"):
            if any(part in (".git", "node_modules", "__pycache__", ".venv")
                   for part in p.parts):
                continue
            if p.is_file():
                rel = p.relative_to(zip_root).as_posix()
                zf.write(p, path_prefix + rel)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )


# ---------- BYO AGENTS ----------


@api.get("/agents")
async def list_agents(user: dict = Depends(get_current_user)):
    docs = await db.user_agents.find(
        {"user_id": user["user_id"]}, {"_id": 0, "endpoint_key_ct": 0}
    ).to_list(50)
    return {"agents": docs}


@api.post("/agents")
async def create_agent(payload: dict, user: dict = Depends(get_current_user)):
    name = (payload.get("name") or "").strip()
    system_prompt = payload.get("system_prompt") or ""
    provider = payload.get("provider", "gemini")
    model = payload.get("model") or "gemini-3-flash-preview"
    endpoint = payload.get("endpoint")  # optional external endpoint
    endpoint_key = payload.get("endpoint_key")  # optional
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    doc = {
        "agent_id": agent_id,
        "user_id": user["user_id"],
        "name": name,
        "system_prompt": system_prompt,
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if endpoint_key:
        doc["endpoint_key_ct"] = encrypt_key(endpoint_key)
    await db.user_agents.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("endpoint_key_ct", None)
    return doc


@api.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, user: dict = Depends(get_current_user)):
    await db.user_agents.delete_one({"agent_id": agent_id, "user_id": user["user_id"]})
    return {"ok": True}


# ---------- HEALTH ----------

@api.get("/ai/telemetry")
async def ai_telemetry(limit: int = 5, user: dict = Depends(get_current_user)):
    """Return the last N LLM chain calls for the current user."""
    limit = max(1, min(int(limit), 50))
    docs = await db.llm_telemetry.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", -1).to_list(limit)
    return {"events": docs}


@api.post("/ai/agent")
async def ai_agent(payload: dict, user: dict = Depends(get_current_user)):
    """Agentic chat — J plans, calls tools, returns transcript."""
    project_id = payload.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    base = project_path(user["user_id"], project_id)
    message = payload.get("message", "")
    conversation_id = payload.get("conversation_id") or f"agent_{uuid.uuid4().hex[:10]}"
    max_steps = int(payload.get("max_steps", 6))

    # Build resumable transcript: prior history + this user message
    history = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(200)
    transcript_for_llm: list[str] = []
    for h in history:
        role = h.get("role")
        if role == "user":
            transcript_for_llm.append(f"[USER]\n{h['content']}")
        elif role == "assistant":
            transcript_for_llm.append(f"[J]\n{h['content']}")
        elif role == "tool":
            transcript_for_llm.append(f"[TOOL RESULT — {h.get('name')}]\n{h.get('content','')[:1500]}")

    await db.messages.insert_one({
        "conversation_id": conversation_id, "user_id": user["user_id"],
        "role": "user", "content": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    transcript_for_llm.append(f"[USER]\n{message}")

    # Recursive Temporal Persistence — index, profile, recall
    await associative_record(db, user["user_id"], project_id=project_id,
                              role="user", content=message, kind="chat")
    await heuristic_update(db, user["user_id"], message)
    recalled = await associative_recall(db, user["user_id"], query=message,
                                         k=5, project_id=project_id)
    signature = await heuristic_get(db, user["user_id"])
    sig_line = render_signature(signature)
    if recalled or sig_line:
        ctx_block = ["[J:MEMORY]"]
        if sig_line:
            ctx_block.append(sig_line)
        if recalled:
            ctx_block.append("Top relevant past context:")
            for r in recalled:
                ctx_block.append(f"  - ({r['score']}) [{r['role']}] {r['content'][:200]}")
        transcript_for_llm.append("\n".join(ctx_block))

    gh_token = await _resolve_github_token(user["user_id"])
    ctx = ToolContext(base=base, user_id=user["user_id"],
                      project_id=project_id, github_token=gh_token)

    steps: list[dict[str, Any]] = []
    done_reason: Optional[str] = None
    final_summary = ""

    for step_idx in range(max_steps):
        user_text = "\n\n".join(transcript_for_llm) + "\n\n[J]\n"
        reply, meta = await _chain_call(
            user["user_id"], "chat", AGENT_PROMPT, user_text,
            f"{user['user_id']}-agent-{conversation_id}-{step_idx}",
        )
        if not meta["success"]:
            done_reason = "llm_chain_exhausted"
            final_summary = "// J:OFFLINE — LLM chain exhausted. Configure provider keys in Settings."
            steps.append({"type": "assistant", "text": final_summary, "meta": meta})
            break

        prose = strip_tool_calls(reply)
        calls = parse_tool_calls(reply)
        steps.append({"type": "assistant", "text": prose, "raw": reply, "meta": meta})
        transcript_for_llm.append(f"[J]\n{reply}")

        if not calls:
            done_reason = "no_tool_calls"
            final_summary = prose
            break

        ask_user_question: Optional[str] = None
        is_done = False
        for call in calls:
            result = await execute_tool(ctx, call["name"], call.get("args", {}))
            # Code-signed log entry (no LLM involvement)
            try:
                log_tool_event(base, signer="J", tool=call["name"],
                               args=call.get("args", {}), result=result)
            except OSError as e:
                log.warning(f"migration log write failed: {e}")
            steps.append({"type": "tool", "name": call["name"], "args": call.get("args", {}),
                          "result": result})
            # Chronos + Associative — code-driven, deterministic
            try:
                chronos_append(
                    base,
                    event_type="tool_call",
                    file=call.get("args", {}).get("path"),
                    action=call["name"],
                    rationale=prose[:200] if prose else "",
                    sentiment="rejection" if result.get("error") else "approval",
                    actor="J",
                    extra={"exit": result.get("exit_code"),
                           "blocked": "BLOCKED" in (result.get("error", "") or "")},
                )
            except OSError:
                pass
            await associative_record(
                db, user["user_id"], project_id=project_id,
                role="tool", content=f"{call['name']} -> {json.dumps(result)[:600]}",
                kind="tool",
            )
            await db.messages.insert_one({
                "conversation_id": conversation_id, "user_id": user["user_id"],
                "role": "tool", "name": call["name"],
                "content": json.dumps({"args": call.get("args", {}), "result": result})[:6000],
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            transcript_for_llm.append(f"[TOOL RESULT — {call['name']}]\n{json.dumps(result)[:1500]}")

            if result.get("_done"):
                is_done = True
                final_summary = result.get("summary", "")
                done_reason = "done_tool"
                break
            if result.get("_ask_user"):
                ask_user_question = result.get("question", "")
                done_reason = "awaiting_user"
                break

        if is_done or ask_user_question:
            break
    else:
        done_reason = "max_steps_reached"
        final_summary = "// Stopped at max_steps. Send another message to continue."

    # Persist the final J message
    await db.messages.insert_one({
        "conversation_id": conversation_id, "user_id": user["user_id"],
        "role": "assistant", "content": final_summary,
        "ts": datetime.now(timezone.utc).isoformat(),
        "steps_count": len(steps),
        "done_reason": done_reason,
    })

    return {
        "conversation_id": conversation_id,
        "steps": steps,
        "final": final_summary,
        "done_reason": done_reason,
    }


@api.get("/ai/agent/history")
async def ai_agent_history(conversation_id: str, user: dict = Depends(get_current_user)):
    docs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(500)
    return {"messages": docs}


@api.get("/ai/chain")
async def ai_chain(user: dict = Depends(get_current_user)):
    """Show the resolved failover chain for each task (which steps will actually run)."""
    private_mode = bool(user.get("private_mode", False))
    out: dict[str, list[dict]] = {}
    for task, steps in TASK_CHAINS.items():
        resolved = []
        for source, provider, model in steps:
            if source == "universal":
                runnable = bool(EMERGENT_LLM_KEY)
                shown_model = model
            else:
                cfg = await _resolve_byok(user["user_id"], provider)
                runnable = bool(cfg)
                if provider == "ollama" and runnable and isinstance(cfg, dict):
                    shown_model = cfg.get("default_model", model)
                else:
                    shown_model = model
            # Private Mode: only ollama is allowed to run
            if private_mode and provider != "ollama":
                runnable = False
            resolved.append({
                "source": source, "provider": provider, "model": shown_model,
                "runnable": runnable,
            })
        out[task] = resolved
    return {"chains": out, "private_mode": private_mode}


@api.get("/")
async def root():
    return {
        "name": "Gauntlet DevSpace",
        "tagline": "DETERMINISTIC. AUTONOMOUS. SUBSTRATE.",
        "status": "online",
    }


# ---------- MOUNT ----------

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    client.close()
