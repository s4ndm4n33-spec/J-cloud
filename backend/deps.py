"""Shared FastAPI dependencies and helpers.

Houses the DB client, auth resolution, workspace path helpers, project seeding,
and the destructive-override consume helper. Route modules import from here.
"""
from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Cookie, Depends, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
WORKSPACE_ROOT = Path(os.environ["WORKSPACE_ROOT"])
OVERRIDE_PASSWORD = os.environ["OVERRIDE_PASSWORD"]
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

log = logging.getLogger("gauntlet")


# ---------- Auth ----------

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


async def user_from_token(token: Optional[str], cookie_token: Optional[str]) -> Optional[dict]:
    """WebSocket-friendly user resolver. Accepts either ?token= or cookie."""
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


# ---------- Workspace paths + seeding ----------

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
    try:
        subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "j@sovereign.shards"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "J"], cwd=path, check=True)
        subprocess.run(["git", "add", "."], cwd=path, check=True, timeout=10)
        subprocess.run(["git", "commit", "-q", "-m", "Initial shard"], cwd=path, check=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning(f"git init failed: {e}")


def user_root(user_id: str) -> Path:
    p = WORKSPACE_ROOT / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def project_path(user_id: str, project_id: str) -> Path:
    p = user_root(user_id) / project_id
    if not p.exists():
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


async def require_project(user: dict, project_id: str) -> dict:
    proj = await db.projects.find_one(
        {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


# ---------- Destructive override (consume-once token) ----------

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


# Public exports
CurrentUser = Depends(get_current_user)
