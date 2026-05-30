"""J's tool belt — file/git/exec/audit/web tools for the agentic chat loop."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Awaitable

import httpx

from .destructive import scan as destructive_scan, scan_command


# ---------- TOOL SPEC (advertised to the LLM) ----------

TOOL_SPEC: list[dict[str, Any]] = [
    # Filesystem
    {"name": "create_file", "desc": "Create a NEW file (fails if exists).",
     "args": {"path": "string (relative)", "content": "string"}},
    {"name": "write_file", "desc": "Write/overwrite a file.",
     "args": {"path": "string", "content": "string"}},
    {"name": "append_file", "desc": "Append to a file (creates if missing).",
     "args": {"path": "string", "content": "string"}},
    {"name": "read_file", "desc": "Read a file's text content.",
     "args": {"path": "string"}},
    {"name": "delete_file", "desc": "Delete a file or directory.",
     "args": {"path": "string"}},
    {"name": "create_folder", "desc": "Create a directory (mkdir -p).",
     "args": {"path": "string"}},
    {"name": "move_file", "desc": "Move/rename.",
     "args": {"src": "string", "dst": "string"}},
    {"name": "list_dir", "desc": "List a directory's entries.",
     "args": {"path": "string (default '.')"}},
    # Search
    {"name": "search_code", "desc": "Recursive text search across workspace.",
     "args": {"query": "string", "glob": "optional glob"}},
    {"name": "find_files", "desc": "Glob-match file paths.",
     "args": {"pattern": "glob like '**/*.py'"}},
    # Exec
    {"name": "run_command", "desc": "Run a shell command in the workspace (destructive patterns halt and require user override).",
     "args": {"cmd": "string", "timeout": "int seconds (default 30)"}},
    # Git
    {"name": "git_status", "desc": "Show git status.", "args": {}},
    {"name": "git_commit", "desc": "git add . && git commit -m <message>.",
     "args": {"message": "string"}},
    # GitHub (require PAT)
    {"name": "github_clone", "desc": "Clone a GitHub repo INTO a new sibling workspace (returns project_id; current workspace unchanged).",
     "args": {"clone_url": "string"}},
    # Gauntlet
    {"name": "gauntlet_evaluate", "desc": "Run Five Masters AST on a file.",
     "args": {"path": "string"}},
    {"name": "project_audit", "desc": "Run the 100-point project audit.",
     "args": {}},
    # Web
    {"name": "web_fetch", "desc": "GET a URL and return the first 8000 chars of text (for docs lookup).",
     "args": {"url": "string"}},
    # Control
    {"name": "ask_user", "desc": "Pause and ask the user a question. Use BEFORE bulk mutations (>5 files) or any irreversible action.",
     "args": {"question": "string"}},
    {"name": "done", "desc": "Signal that the task is complete. The 'summary' goes to the user.",
     "args": {"summary": "string"}},
]


def render_tool_spec() -> str:
    lines = ["# Available tools (call with <tool_call> JSON):\n"]
    for t in TOOL_SPEC:
        args_str = ", ".join(f"{k}: {v}" for k, v in t["args"].items()) or "no args"
        lines.append(f"- **{t['name']}**({args_str}) — {t['desc']}")
    return "\n".join(lines)


# ---------- PARSING ----------

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    out = []
    for m in TOOL_CALL_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj.get("name"):
                out.append({"name": obj["name"], "args": obj.get("args", {})})
        except json.JSONDecodeError:
            continue
    return out


def strip_tool_calls(text: str) -> str:
    return TOOL_CALL_RE.sub("", text).strip()


# ---------- EXECUTOR ----------


class ToolContext:
    def __init__(self, base: Path, user_id: str, project_id: str,
                 github_token: str | None = None) -> None:
        self.base = base
        self.user_id = user_id
        self.project_id = project_id
        self.github_token = github_token
        self.pending_override: dict[str, Any] | None = None


def _safe(base: Path, rel: str) -> Path:
    rel = (rel or "").lstrip("/")
    candidate = (base / rel).resolve()
    root = base.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"Path escapes workspace: {rel}")
    return candidate


async def _tool_create_file(ctx: ToolContext, path: str, content: str = "") -> dict:
    target = _safe(ctx.base, path)
    if target.exists():
        return {"error": "File already exists. Use write_file to overwrite."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"ok": True, "path": path, "bytes": len(content)}


async def _tool_write_file(ctx: ToolContext, path: str, content: str = "") -> dict:
    target = _safe(ctx.base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"ok": True, "path": path, "bytes": len(content)}


async def _tool_append_file(ctx: ToolContext, path: str, content: str = "") -> dict:
    target = _safe(ctx.base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(content)
    return {"ok": True, "path": path, "bytes_appended": len(content)}


async def _tool_read_file(ctx: ToolContext, path: str) -> dict:
    target = _safe(ctx.base, path)
    if not target.exists() or not target.is_file():
        return {"error": f"Not a file: {path}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": "Binary file"}
    return {"path": path, "content": content[:20000], "truncated": len(content) > 20000}


async def _tool_delete_file(ctx: ToolContext, path: str) -> dict:
    target = _safe(ctx.base, path)
    if not target.exists():
        return {"error": f"Not found: {path}"}
    matches = destructive_scan(f"delete {path}")
    if any(m.severity == "critical" for m in matches):
        return {"error": "BLOCKED by destructive scan", "matches": [m.__dict__ for m in matches]}
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True, "deleted": path}


async def _tool_create_folder(ctx: ToolContext, path: str) -> dict:
    target = _safe(ctx.base, path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": path}


async def _tool_move_file(ctx: ToolContext, src: str, dst: str) -> dict:
    s = _safe(ctx.base, src); d = _safe(ctx.base, dst)
    if not s.exists():
        return {"error": f"Source missing: {src}"}
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return {"ok": True, "from": src, "to": dst}


async def _tool_list_dir(ctx: ToolContext, path: str = ".") -> dict:
    target = _safe(ctx.base, path)
    if not target.is_dir():
        return {"error": f"Not a directory: {path}"}
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name in (".git", "node_modules", "__pycache__"):
            continue
        entries.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
    return {"path": path, "entries": entries}


async def _tool_search_code(ctx: ToolContext, query: str, glob: str = "**/*") -> dict:
    hits = []
    for p in ctx.base.glob(glob):
        if any(s in p.parts for s in (".git", "node_modules", "__pycache__")):
            continue
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append({"file": p.relative_to(ctx.base).as_posix(), "line": i, "text": line.strip()[:200]})
                if len(hits) >= 30:
                    return {"query": query, "hits": hits, "truncated": True}
    return {"query": query, "hits": hits, "truncated": False}


async def _tool_find_files(ctx: ToolContext, pattern: str) -> dict:
    matches = []
    for p in ctx.base.glob(pattern):
        if any(s in p.parts for s in (".git", "node_modules", "__pycache__")):
            continue
        matches.append(p.relative_to(ctx.base).as_posix())
        if len(matches) >= 100:
            break
    return {"pattern": pattern, "matches": matches}


async def _tool_run_command(ctx: ToolContext, cmd: str, timeout: int = 30) -> dict:
    matches = scan_command(cmd)
    if any(m.severity == "critical" for m in matches):
        return {"error": "BLOCKED — destructive pattern detected. Surface this to the user and request password override.",
                "matches": [m.__dict__ for m in matches]}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(ctx.base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:8000],
            "stderr": stderr.decode("utf-8", errors="replace")[:4000],
        }
    except asyncio.TimeoutError:
        return {"error": f"Timeout after {timeout}s"}


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, "", str(e)


async def _tool_git_status(ctx: ToolContext) -> dict:
    code, out, err = _git(["status", "--porcelain", "-b"], ctx.base)
    return {"ok": code == 0, "output": out, "error": err if code else None}


async def _tool_git_commit(ctx: ToolContext, message: str) -> dict:
    _git(["add", "."], ctx.base)
    code, out, err = _git(["commit", "-m", message], ctx.base)
    return {"ok": code == 0, "stdout": out, "stderr": err}


async def _tool_github_clone(ctx: ToolContext, clone_url: str) -> dict:
    if not ctx.github_token:
        return {"error": "GitHub not connected. Ask the user to connect a PAT in the GitHub panel."}
    # Defer to the regular endpoint flow — keep this tool's surface area thin.
    return {"hint": "Call POST /api/github/clone via the GitHub panel UI. Direct tool clone disabled in agent loop to keep new workspace handoff clean."}


async def _tool_gauntlet_evaluate(ctx: ToolContext, path: str) -> dict:
    from .fivemasters import evaluate as fm_evaluate
    target = _safe(ctx.base, path)
    if not target.is_file():
        return {"error": f"Not a file: {path}"}
    text = target.read_text(encoding="utf-8", errors="ignore")
    lang = {
        ".py": "python", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
    }.get(target.suffix.lower(), "plaintext")
    rep = fm_evaluate(text, lang).to_dict()
    return {"path": path, "score": rep["score"], "masters": rep["masters"], "issues": rep["issues"][:10]}


async def _tool_project_audit(ctx: ToolContext) -> dict:
    from .scoring import audit_project
    audit = audit_project(ctx.base)
    return {
        "score": audit["score"], "grade": audit["grade"], "file_count": audit["file_count"],
        "breakdown": audit["breakdown"],
        "top_recommendations": audit["recommendations"][:5],
    }


async def _tool_web_fetch(ctx: ToolContext, url: str) -> dict:
    if not re.match(r"^https?://", url):
        return {"error": "URL must start with http:// or https://"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Sovereign-Shards-J/1.0"})
        text = r.text[:8000]
        return {"url": url, "status": r.status_code, "content": text, "truncated": len(r.text) > 8000}
    except (httpx.HTTPError, OSError) as e:
        return {"error": str(e)[:200]}


async def _tool_ask_user(ctx: ToolContext, question: str) -> dict:
    # The loop short-circuits on this — frontend will render and pause.
    return {"_ask_user": True, "question": question}


async def _tool_done(ctx: ToolContext, summary: str = "") -> dict:
    return {"_done": True, "summary": summary}


HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    "create_file": _tool_create_file,
    "write_file": _tool_write_file,
    "append_file": _tool_append_file,
    "read_file": _tool_read_file,
    "delete_file": _tool_delete_file,
    "create_folder": _tool_create_folder,
    "move_file": _tool_move_file,
    "list_dir": _tool_list_dir,
    "search_code": _tool_search_code,
    "find_files": _tool_find_files,
    "run_command": _tool_run_command,
    "git_status": _tool_git_status,
    "git_commit": _tool_git_commit,
    "github_clone": _tool_github_clone,
    "gauntlet_evaluate": _tool_gauntlet_evaluate,
    "project_audit": _tool_project_audit,
    "web_fetch": _tool_web_fetch,
    "ask_user": _tool_ask_user,
    "done": _tool_done,
}


async def execute_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict:
    fn = HANDLERS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await fn(ctx, **args)
    except TypeError as e:
        return {"error": f"Bad args for {name}: {e}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:300]}
