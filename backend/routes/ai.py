"""AI Coworker routes — chat / refine / governance / agent / telemetry / chain."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, log, project_path, EMERGENT_LLM_KEY
from core.agent_prompt import AGENT_PROMPT
from core.destructive import scan as destructive_scan
from core.fivemasters import evaluate as fm_evaluate
from core.keyvault import decrypt_key
from core.migration_log import log_tool_event
from core.persistence import (
    associative_recall, associative_record, chronos_append,
    heuristic_get, heuristic_update, render_signature,
)
from core.persona import CHAT_PROMPT, REFINE_PROMPT, GOVERNANCE_PROMPT
from core.tools import ToolContext, execute_tool, parse_tool_calls, strip_tool_calls
from core import chronicle as chron
from llm_chain import TASK_CHAINS, chain_call, resolve_byok
from chronicle_helpers import chronicle_narrative, chronicle_session_start

router = APIRouter()


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


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.rstrip() + "\n"


async def _resolve_github_token(user_id: str) -> Optional[str]:
    doc = await db.user_github.find_one({"user_id": user_id}, {"_id": 0})
    if doc and doc.get("ciphertext"):
        try:
            return decrypt_key(doc["ciphertext"])
        except (ValueError, TypeError):
            log.warning(f"github token decrypt failed for {user_id}")
    return None


@router.post("/ai/chat")
async def ai_chat(payload: dict, user: dict = Depends(get_current_user)):
    """Gemini-first chat with BYOK failover chain."""
    conversation_id = payload.get("conversation_id") or f"conv_{uuid.uuid4().hex[:10]}"
    message = payload.get("message", "")
    project_id = payload.get("project_id")
    ctx = _build_context_block(payload)
    user_text = f"{ctx}\n\n[USER]\n{message}" if ctx else message

    if project_id:
        proj = await db.projects.find_one(
            {"project_id": project_id, "user_id": user["user_id"]}, {"_id": 1},
        )
        if proj:
            await chronicle_session_start(
                project_id, user["user_id"], conversation_id, message,
            )

    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "user",
        "content": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    reply, meta = await chain_call(
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


@router.get("/ai/chat/history")
async def ai_chat_history(conversation_id: str, user: dict = Depends(get_current_user)):
    docs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(500)
    return {"messages": docs}


@router.post("/ai/refine")
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
    reply, meta = await chain_call(
        user["user_id"], "refine", REFINE_PROMPT, user_text,
        f"{user['user_id']}-refine-{uuid.uuid4().hex[:6]}",
    )
    if not meta["success"]:
        raise HTTPException(status_code=502, detail={
            "message": "LLM failover chain exhausted",
            "attempts": meta["attempts"],
        })
    refined = _strip_code_fences(reply)
    ast_report = fm_evaluate(refined, language).to_dict()
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


@router.post("/ai/governance")
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
    raw, meta = await chain_call(
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


@router.get("/ai/telemetry")
async def ai_telemetry(limit: int = 5, user: dict = Depends(get_current_user)):
    """Return the last N LLM chain calls for the current user."""
    limit = max(1, min(int(limit), 50))
    docs = await db.llm_telemetry.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", -1).to_list(limit)
    return {"events": docs}


@router.post("/ai/agent")
async def ai_agent(payload: dict, user: dict = Depends(get_current_user)):
    """Agentic chat — J plans, calls tools, returns transcript."""
    project_id = payload.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    base = project_path(user["user_id"], project_id)
    message = payload.get("message", "")
    conversation_id = payload.get("conversation_id") or f"agent_{uuid.uuid4().hex[:10]}"
    max_steps = int(payload.get("max_steps", 6))

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

    await chronicle_session_start(project_id, user["user_id"], conversation_id, message)

    await db.messages.insert_one({
        "conversation_id": conversation_id, "user_id": user["user_id"],
        "role": "user", "content": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    transcript_for_llm.append(f"[USER]\n{message}")

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
        reply, meta = await chain_call(
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
            try:
                log_tool_event(base, signer="J", tool=call["name"],
                               args=call.get("args", {}), result=result)
            except OSError as e:
                log.warning(f"migration log write failed: {e}")
            try:
                err = result.get("error")
                milestone_tools = {
                    "create_file", "write_file", "delete_file", "move_file",
                    "extract_zip", "install_deps", "build_project",
                    "git_commit", "run_command",
                }
                if err or call["name"] in milestone_tools:
                    args_dict = call.get("args", {}) or {}
                    target = args_dict.get("path") or args_dict.get("command") or ""
                    title = f"{'FAIL' if err else 'OK'} · {call['name']}"
                    if target:
                        title += f" · {str(target)[:80]}"
                    body_lines = []
                    if err:
                        body_lines.append(f"**Error:** {str(err)[:400]}")
                    elif result.get("exit_code") not in (None, 0):
                        body_lines.append(f"**Exit code:** {result.get('exit_code')}")
                    for k in ("files_written", "files_skipped", "total_bytes",
                              "deleted", "to", "detected"):
                        if k in result:
                            body_lines.append(f"**{k}:** {result[k]}")
                    await chron.append_entry(
                        db, base,
                        project_id=project_id, user_id=user["user_id"],
                        session_id=conversation_id,
                        kind="tool", signer="J", title=title,
                        body="\n".join(body_lines),
                        tags=["tool", call["name"]] + (["fail"] if err else []),
                    )
            except Exception as e:
                log.warning(f"chronicle tool-mirror failed: {e}")
            steps.append({"type": "tool", "name": call["name"], "args": call.get("args", {}),
                          "result": result})
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

    await db.messages.insert_one({
        "conversation_id": conversation_id, "user_id": user["user_id"],
        "role": "assistant", "content": final_summary,
        "ts": datetime.now(timezone.utc).isoformat(),
        "steps_count": len(steps),
        "done_reason": done_reason,
    })

    if done_reason in {"done_tool", "no_tool_calls", "max_steps_reached"}:
        tool_summary = []
        for s in steps:
            if s.get("type") == "tool":
                tn = s.get("name", "?")
                args = s.get("args", {}) or {}
                path = args.get("path") or args.get("command") or ""
                err = (s.get("result") or {}).get("error")
                tag = "FAIL" if err else "OK"
                tool_summary.append(f"{tag} · {tn}({str(path)[:80]})")
        try:
            await chronicle_narrative(
                user_id=user["user_id"], project_id=project_id,
                session_id=conversation_id,
                user_first_msg=message, tool_summary=tool_summary,
                final_summary=final_summary,
            )
        except Exception as e:
            log.warning(f"chronicle narrative append failed: {e}")

    return {
        "conversation_id": conversation_id,
        "steps": steps,
        "final": final_summary,
        "done_reason": done_reason,
    }


@router.get("/ai/agent/history")
async def ai_agent_history(conversation_id: str, user: dict = Depends(get_current_user)):
    docs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(500)
    return {"messages": docs}


@router.get("/ai/chain")
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
                cfg = await resolve_byok(user["user_id"], provider)
                runnable = bool(cfg)
                if provider == "ollama" and runnable and isinstance(cfg, dict):
                    shown_model = cfg.get("default_model", model)
                else:
                    shown_model = model
            if private_mode and provider != "ollama":
                runnable = False
            resolved.append({
                "source": source, "provider": provider, "model": shown_model,
                "runnable": runnable,
            })
        out[task] = resolved
    return {"chains": out, "private_mode": private_mode}
