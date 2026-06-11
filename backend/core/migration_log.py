"""Migration log — append-only build timeline per project workspace.

Code-driven, not LLM-driven. Every entry is timestamped and signed.
Stored at `.gauntlet/migration.log.md` inside the project root so it travels with
the workspace (zip download, git push, etc.).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOG_REL = ".gauntlet/migration.log.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_path(project_root: Path) -> Path:
    return project_root / LOG_REL


def ensure_log(project_root: Path, signer: str = "SYSTEM") -> Path:
    """Create the log file with a header if it doesn't exist."""
    p = _log_path(project_root)
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Migration Log — Sovereign Shards / Gauntlet DevSpace\n\n"
        "> Append-only build timeline. Every entry is code-signed and dated.\n"
        "> Do not edit older entries; add a new one instead.\n\n"
        f"_initialized {_now_iso()} by {signer}_\n\n"
        "---\n\n"
    )
    p.write_text(header, encoding="utf-8")
    return p


def append_entry(
    project_root: Path,
    *,
    signer: str,
    title: str,
    problem: Optional[str] = None,
    fix: Optional[str] = None,
    why: Optional[str] = None,
    next_step: Optional[str] = None,
    tags: Optional[list[str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append a structured entry to the migration log. Returns the entry dict."""
    p = ensure_log(project_root, signer=signer)
    ts = _now_iso()
    tag_str = " ".join(f"`{t}`" for t in (tags or []))
    parts = [
        f"## {ts} — {title}",
        f"_signed: **{signer}**_  {tag_str}".rstrip(),
    ]
    if problem:
        parts.append(f"\n**Problem.** {problem.strip()}")
    if fix:
        parts.append(f"\n**Fix.** {fix.strip()}")
    if why:
        parts.append(f"\n**Why.** {why.strip()}")
    if next_step:
        parts.append(f"\n**Next step.** {next_step.strip()}")
    if extra:
        parts.append("\n```json\n" + json.dumps(extra, indent=2, default=str) + "\n```")
    parts.append("\n---\n")
    block = "\n".join(parts) + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(block)
    return {
        "ts": ts, "signer": signer, "title": title, "problem": problem,
        "fix": fix, "why": why, "next_step": next_step,
        "tags": tags or [], "extra": extra or {},
    }


def log_session_start(project_root: Path, *, conversation_id: str, user_id: str) -> None:
    """Called automatically on the first agent tool call of a conversation."""
    append_entry(
        project_root,
        signer="SYSTEM",
        title=f"Session start · {conversation_id[:18]}",
        tags=["session"],
        extra={"conversation_id": conversation_id, "user_id": user_id},
    )


def log_tool_event(
    project_root: Path,
    *,
    signer: str,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Code-signed entry whenever a tool fails OR succeeds at a milestone op."""
    error = result.get("error")
    milestone_tools = {
        "create_file", "write_file", "delete_file", "move_file", "extract_zip",
        "install_deps", "build_project", "git_commit", "run_command",
    }
    if not error and tool not in milestone_tools:
        return
    title_prefix = "FAIL" if error else "OK"
    title = f"{title_prefix} · {tool}"
    if error:
        append_entry(
            project_root,
            signer=signer,
            title=title,
            problem=f"`{tool}` failed: {str(error)[:300]}",
            tags=["tool", "fail", tool],
            extra={"args": args, "result_keys": list(result.keys())[:10]},
        )
    else:
        # Compact OK entries — title + tags + minimal extra
        compact: dict[str, Any] = {}
        for k in ("path", "exit_code", "files_written", "files_skipped",
                  "total_bytes", "detected", "deleted", "to"):
            if k in result:
                compact[k] = result[k]
        append_entry(
            project_root,
            signer=signer,
            title=title,
            tags=["tool", tool],
            extra={"args": args, **compact},
        )


def log_audit(project_root: Path, *, signer: str, score: float, grade: str,
              top_recommendation: Optional[str] = None) -> None:
    append_entry(
        project_root,
        signer=signer,
        title=f"Audit · {score}/100 ({grade})",
        tags=["audit"],
        next_step=top_recommendation,
        extra={"score": score, "grade": grade},
    )


def log_manual(
    project_root: Path,
    *,
    signer: str,
    title: str,
    problem: str = "",
    fix: str = "",
    why: str = "",
    next_step: str = "",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    return append_entry(
        project_root,
        signer=signer,
        title=title,
        problem=problem or None,
        fix=fix or None,
        why=why or None,
        next_step=next_step or None,
        tags=tags or ["manual"],
    )


def read_log(project_root: Path) -> str:
    p = _log_path(project_root)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")
