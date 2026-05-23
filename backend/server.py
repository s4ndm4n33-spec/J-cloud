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
from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from core.destructive import scan as destructive_scan, scan_command
from core.fivemasters import evaluate as fm_evaluate
from core.persona import CHAT_PROMPT, REFINE_PROMPT, GOVERNANCE_PROMPT

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
    return {"user": user}


@api.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return user


@api.post("/auth/logout")
async def auth_logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
):
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
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
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {"stdout": "", "stderr": "Timeout (30s)", "exit_code": 124}
    except OSError as e:
        return {"stdout": "", "stderr": f"Exec error: {e}", "exit_code": 1}


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


async def _llm_call(provider: str, model: str, system: str, user_text: str,
                    session_id: str) -> str:
    """Make a single LLM call via emergentintegrations."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=user_text))
    return resp if isinstance(resp, str) else str(resp)


@api.post("/ai/chat")
async def ai_chat(payload: dict, user: dict = Depends(get_current_user)):
    """Gemini-powered chat with project context."""
    conversation_id = payload.get("conversation_id") or f"conv_{uuid.uuid4().hex[:10]}"
    message = payload.get("message", "")
    ctx = _build_context_block(payload)
    user_text = f"{ctx}\n\n[USER]\n{message}" if ctx else message

    # Persist user msg
    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "user",
        "content": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    try:
        reply = await _llm_call(
            "gemini", "gemini-3-flash-preview",
            CHAT_PROMPT, user_text, f"{user['user_id']}-{conversation_id}",
        )
    except Exception as e:  # broad - emergentintegrations raises ChatError
        log.exception("gemini chat failed")
        reply = (
            "// J:OFFLINE — LLM provider returned an error.\n"
            f"// detail: {e}\n"
            "// (If 'Budget exceeded': top up at Profile → Universal Key → Add Balance.)\n"
        )

    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {"conversation_id": conversation_id, "reply": reply}


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
    try:
        refined = await _llm_call(
            "openai", "gpt-5.2",
            REFINE_PROMPT, user_text, f"{user['user_id']}-refine-{uuid.uuid4().hex[:6]}",
        )
    except Exception as e:
        log.exception("gpt refine failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    refined = _strip_code_fences(refined)

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
    try:
        raw = await _llm_call(
            "anthropic", "claude-sonnet-4-5-20250929",
            GOVERNANCE_PROMPT, user_text,
            f"{user['user_id']}-gov-{uuid.uuid4().hex[:6]}",
        )
    except Exception as e:
        log.exception("claude governance failed")
        # Fall back to AST report only
        return {
            "ast_report": ast_report,
            "llm_verdict": {
                "verdict": "PASS" if ast_report["score"] == 5 else "FAIL",
                "summary": f"AST-only fallback (LLM unavailable): {e}",
                "masters": ast_report["masters"],
                "fixes": [iss["message"] for iss in ast_report["issues"][:5]],
            },
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

    return {"ast_report": ast_report, "llm_verdict": parsed}


# ---------- HEALTH ----------

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
