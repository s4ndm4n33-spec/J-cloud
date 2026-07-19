"""AI Coworker routes — chat / refine / governance / agent / telemetry / chain."""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from deps import db, get_current_user, log, project_path, EMERGENT_LLM_KEY, TAVILY_API_KEY, OWNER_USER_ID
from core.agent_prompt import AGENT_PROMPT
from core.destructive import scan as destructive_scan
from core.fivemasters import evaluate as fm_evaluate
from core.guardrails import redact_substrate_leaks
from core.keyvault import decrypt_key
from core.migration_log import log_tool_event
from core import knowledge as km
from core.persistence import (
    associative_recall, associative_record, chronos_append,
    heuristic_get, heuristic_update, render_signature,
)
from core.persona import CHAT_PROMPT, REFINE_PROMPT, GOVERNANCE_PROMPT
from core.ratelimit import take as ratelimit_take
from core.tools import ToolContext, execute_tool, parse_tool_calls, strip_tool_calls
from core import chronicle as chron
from llm_chain import TASK_CHAINS, chain_call, resolve_byok
from chronicle_helpers import chronicle_narrative, chronicle_session_start

router = APIRouter()

# Rate limits (owner is exempt — see core/ratelimit.set_owner_id).
# Chat/refine: 12 req/min. Agent: 6 req/min (heavier turns, more tool calls).
_CHAT_CAP, _CHAT_REFILL = 12, 12 / 60.0
_AGENT_CAP, _AGENT_REFILL = 6, 6 / 60.0


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


# --- Auto-verify gate --------------------------------------------------------
# If J mutated code this turn, `done` cannot be honored until J has actually
# run a verification command. Returns an error string if the gate should
# reject the done call, or None if it's fine to proceed.
#
# Rules:
#   - Any write_file / append_file / create_file / delete_file / move_file
#     with a .py/.js/.jsx/.ts/.tsx path counts as "code mutated".
#   - A "verification command" is a run_command whose command line contains
#     pytest / unittest / yarn test / npm test / jest / tsc / mypy / pyright /
#     ruff / eslint. Doesn't matter if it passed — J just has to have HIT the
#     check. If verification FAILED, J was supposed to fix and re-run, but
#     that's J's judgement, not the gate's.
#   - If J only mutated non-code files (.md, .txt, .json, .yaml, config etc.)
#     the gate stands down.
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_VERIFY_TOKENS = (
    "pytest", "unittest", "yarn test", "npm test", "npm run test",
    "jest", "tsc", "mypy", "pyright", "ruff", "eslint",
)


def _check_verification_required(steps: list[dict]) -> Optional[str]:
    code_touched = False
    verified = False
    for s in steps:
        if s.get("type") != "tool":
            continue
        name = s.get("name")
        args = s.get("args") or {}
        res = s.get("result") or {}
        if name in {"write_file", "append_file", "create_file", "delete_file", "move_file"}:
            if res.get("error"):
                continue  # a rejected write doesn't count as "code mutated"
            path = str(args.get("path") or args.get("to") or "").lower()
            if any(path.endswith(ext) for ext in _CODE_SUFFIXES):
                code_touched = True
        elif name == "run_command":
            cmd = str(args.get("command") or "").lower()
            if any(tok in cmd for tok in _VERIFY_TOKENS):
                verified = True
    if code_touched and not verified:
        return (
            "AUTO_VERIFY_HALT: You mutated code this turn but never ran a "
            "verification command. Before calling `done`, run one of: pytest, "
            "yarn test, npm test, tsc --noEmit, mypy, ruff, or eslint — "
            "whichever fits the languages you touched. If tests fail, fix "
            "and re-run. Only THEN call done. This is a deterministic gate — "
            "arguing with it wastes tokens."
        )
    return None
# ----------------------------------------------------------------------------


@router.post("/ai/chat")
async def ai_chat(payload: dict, user: dict = Depends(get_current_user)):
    """Gemini-first chat with BYOK failover chain. Unary."""
    return await _ai_chat_impl(payload, user)


async def _ai_chat_impl(payload: dict, user: dict) -> dict:
    """Core chat logic, callable from both the unary handler and the SSE wrapper."""
    ratelimit_take(user["user_id"], "ai_chat", _CHAT_CAP, _CHAT_REFILL)
    conversation_id = payload.get("conversation_id") or f"conv_{uuid.uuid4().hex[:10]}"
    message = payload.get("message", "")
    project_id = payload.get("project_id")
    ctx = _build_context_block(payload)

    # J:MIND — pull top-K remembered facts relevant to this message and
    # prepend them so plain chat gets sharper with every session too.
    mind_block = ""
    try:
        mind_hits = await km.recall(db, message, k=5)
        mind_block = km.format_recall_for_prompt(mind_hits)
    except Exception as e:
        log.warning(f"mind recall (chat) failed: {e}")

    ctx_parts = [p for p in (ctx, mind_block) if p]
    user_text = ("\n\n".join(ctx_parts) + f"\n\n[USER]\n{message}") if ctx_parts else message

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
        if meta.get("needs_keys"):
            raise HTTPException(status_code=401, detail={
                "code": "needs_keys",
                "message": "Bring your own key. Add an OpenAI / Anthropic / Gemini / Ollama key in Settings to use J.",
                "attempts": meta.get("attempts", []),
            })
        reply = (
            "// J:OFFLINE — entire LLM failover chain exhausted.\n"
            "// Add a provider key in Settings (gear icon) or top up Universal Key balance.\n"
            f"// last attempts: {len(meta['attempts'])}"
        )
    else:
        # Substrate secrecy filter — only apply to actual LLM output, never
        # to synthetic status messages we generated ourselves.
        reply, leak_hits = redact_substrate_leaks(reply)
        if leak_hits:
            log.warning(f"substrate leak redacted (chat) user={user['user_id']} hits={leak_hits[:5]}")
            meta["substrate_redacted"] = True

    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
    })

    # Persist as training data: every J response is a candidate SFT/DPO row.
    # We log to chronicle_entries with kind='ai_answer' so exports can pick it
    # up without a schema migration. `base` is optional (project chain);
    # /ai/chat doesn't have a project scope so we skip the hash chain here
    # and use messages-only for /ai/chat, but tag it as ai_answer for grep.
    try:
        await db.chronicle_entries.insert_one({
            "id": f"chr_{uuid.uuid4().hex[:12]}",
            "kind": "ai_answer",
            "scope": "chat",
            "project_id": project_id or "",
            "session_id": conversation_id,
            "user_id": user["user_id"],
            "prompt": (message or "")[:2000],
            "response": (reply or "")[:6000],
            "model": (meta or {}).get("model_used") or (meta or {}).get("model") or "unknown",
            "provider": (meta or {}).get("provider_used") or (meta or {}).get("provider") or "unknown",
            "verdict": "passed" if reply and not reply.startswith("// J:OFFLINE") else "offline",
            "context_present": bool(ctx_parts),
            "ts": datetime.now(timezone.utc).isoformat(),
            "signer": "J",
        })
    except Exception as e:
        log.warning(f"ai_answer log (chat) failed: {e}")

    return {"conversation_id": conversation_id, "reply": reply, "meta": meta}


# ---------------------------------------------------------------------------
# SSE streaming — keeps bytes flowing through the k8s ingress (120s hard cap)
# by emitting `: heartbeat` comments every ≤15s while the LLM chain runs.
# The final payload is delivered as an `event: done` frame identical to the
# unary endpoint's JSON body.
#
# emergentintegrations exposes only a unary `send_message` — we don't have
# true token streaming, so this is heartbeat-streaming. Adequate for the
# ingress timeout; a UX upgrade to per-step streaming lives in a follow-up.
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 12.0  # seconds — well below the 15s ingress buffer


def _sse_frame(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_task_with_heartbeats(
    coro_factory,
) -> AsyncIterator[str]:
    """Run an awaitable, yielding `: heartbeat` SSE comments every
    _HEARTBEAT_INTERVAL seconds until completion, then a final `event: done`
    frame with the awaited result. On HTTPException, emit `event: error`.
    """
    task = asyncio.create_task(coro_factory())
    try:
        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(task),
                                                timeout=_HEARTBEAT_INTERVAL)
                yield _sse_frame("done", result)
                return
            except asyncio.TimeoutError:
                yield f": heartbeat {int(time.time())}\n\n"
            except HTTPException as e:
                # Task raised HTTPException — surface as an SSE error frame.
                yield _sse_frame("error", {
                    "status": e.status_code,
                    "detail": e.detail,
                })
                return
    except asyncio.CancelledError:  # noqa: BLE001
        task.cancel()
        raise


def _stream_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx hint — disable proxy buffering
            "Connection": "keep-alive",
        },
    )


@router.post("/ai/chat/stream")
async def ai_chat_stream(payload: dict, user: dict = Depends(get_current_user)):
    """SSE variant of /ai/chat. Emits `: heartbeat` comments every 12s so the
    ingress 120s timeout can't fire, then `event: done` with the same JSON
    the unary endpoint returns."""
    async def _run():
        return await _ai_chat_impl(payload, user)
    return _stream_response(_stream_task_with_heartbeats(_run))


@router.get("/ai/chat/history")
async def ai_chat_history(conversation_id: str, user: dict = Depends(get_current_user)):
    docs = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    ).sort("ts", 1).to_list(500)
    return {"messages": docs}


@router.post("/ai/refine")
async def ai_refine(payload: dict, user: dict = Depends(get_current_user)):
    """GPT-5.2 surgical refine. Returns refined code + auto-Gauntlet verdict."""
    ratelimit_take(user["user_id"], "ai_refine", _CHAT_CAP, _CHAT_REFILL)
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
        if meta.get("needs_keys"):
            raise HTTPException(status_code=401, detail={
                "code": "needs_keys",
                "message": "Bring your own key. Add an OpenAI / Anthropic / Gemini / Ollama key in Settings to use J.",
                "attempts": meta.get("attempts", []),
            })
        raise HTTPException(status_code=502, detail={
            "message": "LLM failover chain exhausted",
            "attempts": meta["attempts"],
        })
    refined = _strip_code_fences(reply)
    # Substrate secrecy filter on refined code output too — J shouldn't be
    # coerced into leaking internals via a "refine this file" attack.
    refined, leak_hits = redact_substrate_leaks(refined)
    if leak_hits:
        log.warning(f"substrate leak redacted (refine) user={user['user_id']} hits={leak_hits[:5]}")
        meta["substrate_redacted"] = True
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
        if meta.get("needs_keys"):
            raise HTTPException(status_code=401, detail={
                "code": "needs_keys",
                "message": "Bring your own key. Add an OpenAI / Anthropic / Gemini / Ollama key in Settings to use J.",
                "attempts": meta.get("attempts", []),
            })
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
    return await _ai_agent_impl(payload, user)


async def _ai_agent_impl(payload: dict, user: dict) -> dict:
    """Core agent logic, callable from both the unary handler and the SSE wrapper."""
    ratelimit_take(user["user_id"], "ai_agent", _AGENT_CAP, _AGENT_REFILL)
    project_id = payload.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    base = project_path(user["user_id"], project_id)
    message = payload.get("message", "")
    conversation_id = payload.get("conversation_id") or f"agent_{uuid.uuid4().hex[:10]}"
    max_steps = int(payload.get("max_steps", 40))
    auto_mode = bool(payload.get("auto_mode", False))
    if auto_mode:
        # AUTO MODE: lift the cap so J can chew through multi-file tasks
        # without stopping for handholding. Hard ceiling at 100 to prevent
        # runaway loops if J ever gets stuck calling tools without progress.
        max_steps = max(max_steps, 100)
    max_steps = min(max_steps, 100)

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
    # Wire J's Mind into the tool context so web_search / recall_knowledge /
    # propose_learning can reach Mongo + Tavily without leaking creds through
    # tool args.
    ctx.db = db
    # OWNER LOCK on shared Tavily key: only the app owner gets to spend the
    # shared TAVILY_API_KEY on web_search. Everyone else runs with an empty
    # tavily_key, which makes web_search fail cleanly with a "needs Tavily
    # key" message. (Per-user Tavily BYOK is P1.)
    _is_owner = bool(OWNER_USER_ID) and user["user_id"] == OWNER_USER_ID
    ctx.tavily_key = TAVILY_API_KEY if _is_owner else ""

    # --- J:MIND recall — inject top-K globally learned facts relevant to
    # the user's current message into her system context. This is the
    # "learn from web + accepted proposals" payoff loop.
    try:
        mind_hits = await km.recall(db, message, k=5)
        mind_block = km.format_recall_for_prompt(mind_hits)
        if mind_block:
            transcript_for_llm.append(mind_block)
    except Exception as e:
        log.warning(f"mind recall failed: {e}")

    steps: list[dict[str, Any]] = []
    done_reason: Optional[str] = None
    final_summary = ""
    # Track consecutive turns without tool calls. In AUTO MODE we tolerate 1
    # thinking-out-loud turn (nudge J to continue), then break on the 2nd to
    # avoid infinite prose loops. In non-AUTO, first empty-tool turn breaks
    # immediately, preserving the previous "single-shot with optional tools"
    # behavior for interactive chat.
    no_tool_streak = 0
    NO_TOOL_STREAK_MAX = 2 if auto_mode else 1

    for step_idx in range(max_steps):
        user_text = "\n\n".join(transcript_for_llm) + "\n\n[J]\n"
        reply, meta = await chain_call(
            user["user_id"], "chat", AGENT_PROMPT, user_text,
            f"{user['user_id']}-agent-{conversation_id}-{step_idx}",
        )
        if not meta["success"]:
            if meta.get("needs_keys") and step_idx == 0:
                # First turn already needs BYOK — bail early with 401 so the
                # frontend can route the user to onboarding.
                raise HTTPException(status_code=401, detail={
                    "code": "needs_keys",
                    "message": "Bring your own key. Add an OpenAI / Anthropic / Gemini / Ollama key in Settings to use J.",
                    "attempts": meta.get("attempts", []),
                })
            done_reason = "llm_chain_exhausted"
            final_summary = "// J:OFFLINE — LLM chain exhausted. Configure provider keys in Settings."
            steps.append({"type": "assistant", "text": final_summary, "meta": meta})
            break

        prose = strip_tool_calls(reply)
        calls = parse_tool_calls(reply)
        # Substrate secrecy filter on the prose the user actually sees. Tool
        # calls are unaffected (they're structured invocations, not disclosure).
        prose, prose_leaks = redact_substrate_leaks(prose)
        if prose_leaks:
            log.warning(f"substrate leak redacted (agent step {step_idx}) user={user['user_id']} hits={prose_leaks[:5]}")
            meta["substrate_redacted"] = True
        steps.append({"type": "assistant", "text": prose, "raw": reply, "meta": meta})
        transcript_for_llm.append(f"[J]\n{reply}")

        if not calls:
            no_tool_streak += 1
            if auto_mode and no_tool_streak < NO_TOOL_STREAK_MAX:
                # J emitted prose without a tool call — probably thinking out
                # loud between actions. Nudge and continue rather than stop.
                nudge = (
                    "[AUTO MODE — no tool call detected in your last message.\n"
                    " If your plan has more steps, invoke the next tool now.\n"
                    " If you are TRULY finished, invoke the `done` tool with a\n"
                    " summary. Do NOT stop mid-task by writing prose only.]"
                )
                transcript_for_llm.append(nudge)
                continue
            done_reason = "no_tool_calls"
            final_summary = prose
            break
        no_tool_streak = 0  # reset on any tool-using turn

        ask_user_question: Optional[str] = None
        is_done = False
        for call in calls:
            result = await execute_tool(ctx, call["name"], call.get("args", {}))
            try:
                log_tool_event(base, signer="J", tool=call["name"],
                               args=call.get("args", {}), result=result)
            except OSError as e:
                log.warning(f"migration log write failed: {e}")

            # ---- Special handling: propose_chronicle_entry / screenshot_preview ----
            try:
                if result.get("_propose_chronicle"):
                    pc = result["_propose_chronicle"]
                    entry = await chron.append_entry(
                        db, base,
                        project_id=project_id, user_id=user["user_id"],
                        session_id=conversation_id,
                        kind="proposed", signer="J",
                        title=pc["title"],
                        body=pc["body"],
                        tags=(pc.get("tags") or []) + [f"suggested-kind:{pc['suggested_kind']}"],
                    )
                    result["proposed_entry_hash"] = entry["entry_hash"]
                elif result.get("_snapshot_preview"):
                    sp = result["_snapshot_preview"]
                    note = sp.get("note", "")
                    body_md = (
                        f"**HTML file:** `{sp['html_path']}`\n\n"
                        f"**Snapshot saved at:** `{sp['snapshot_path']}`\n\n"
                        + (f"**Note:** {note}\n" if note else "")
                        + "\n_Open this entry in the Chronicle panel to view the captured render._"
                    )
                    entry = await chron.append_entry(
                        db, base,
                        project_id=project_id, user_id=user["user_id"],
                        session_id=conversation_id,
                        kind="milestone", signer="J",
                        title=f"Design snapshot · {sp['html_path']}",
                        body=body_md,
                        tags=["design-snapshot", f"src:{sp['html_path']}",
                              f"file:{sp['snapshot_path']}"],
                    )
                    result["snapshot_entry_hash"] = entry["entry_hash"]
            except Exception as e:
                log.warning(f"chronicle special-tool mirror failed: {e}")
            # ----------------------------------------------------------------------

            try:
                err = result.get("error")
                milestone_tools = {
                    "create_file", "write_file", "delete_file", "move_file",
                    "extract_zip", "install_deps", "build_project",
                    "git_commit", "run_command",
                }
                # Don't double-mirror tools that already wrote their own chronicle entry
                skip_mirror = call["name"] in {"propose_chronicle_entry", "screenshot_preview"}
                if not skip_mirror and (err or call["name"] in milestone_tools):
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
                # Verification gate: J cannot claim done if he touched code
                # this session and never ran a test / typecheck. This raises
                # the floor from "hopefully works" to "provably ran the check."
                verify_err = _check_verification_required(steps)
                if verify_err:
                    # Rewrite the tool result into a synthetic error so J is
                    # forced to run tests before trying `done` again.
                    result.pop("_done", None)
                    result["error"] = verify_err
                    # Repair the last tool step so the transcript reflects the
                    # rejection (both for J's next-turn context and audit).
                    steps[-1]["result"] = result
                    transcript_for_llm[-1] = (
                        f"[TOOL RESULT — done]\n" + json.dumps(result)[:1500]
                    )
                    continue
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

    # Final substrate-secrecy pass on the summary the user reads at the end.
    final_summary, _sfl = redact_substrate_leaks(final_summary)
    if _sfl:
        log.warning(f"substrate leak redacted (agent final) user={user['user_id']} hits={_sfl[:5]}")

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

    # Persist agent turn as training data (ai_answer row).
    try:
        await db.chronicle_entries.insert_one({
            "id": f"chr_{uuid.uuid4().hex[:12]}",
            "kind": "ai_answer",
            "scope": "agent",
            "project_id": project_id or "",
            "session_id": conversation_id,
            "user_id": user["user_id"],
            "prompt": (message or "")[:2000],
            "response": (final_summary or "")[:6000],
            "model": "agent-loop",
            "provider": "multi",
            "verdict": done_reason or "unknown",
            "steps_taken": len(steps),
            "tool_names": [s.get("tool") for s in steps if s.get("tool")][:20],
            "ts": datetime.now(timezone.utc).isoformat(),
            "signer": "J",
        })
    except Exception as e:
        log.warning(f"ai_answer log (agent) failed: {e}")

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


@router.post("/ai/agent/stream")
async def ai_agent_stream(payload: dict, user: dict = Depends(get_current_user)):
    """SSE variant of /ai/agent. Heartbeats every 12s prevent the ingress 120s
    timeout from firing during long multi-step agent runs. Final result is
    delivered as `event: done` with the same JSON shape as the unary endpoint."""
    async def _run():
        return await _ai_agent_impl(payload, user)
    return _stream_response(_stream_task_with_heartbeats(_run))


@router.get("/ai/chain")
async def ai_chain(user: dict = Depends(get_current_user)):
    """Show the resolved failover chain for each task (which steps will actually run)."""
    private_mode = bool(user.get("private_mode", False))
    is_owner = bool(OWNER_USER_ID) and user["user_id"] == OWNER_USER_ID
    # Pre-fetch all BYOK docs in one hit so we can annotate every step with
    # the user's preferred_model.
    all_byok = {d["provider"]: d async for d in db.user_provider_keys.find(
        {"user_id": user["user_id"]}, {"_id": 0, "ciphertext": 0}
    )}
    out: dict[str, list[dict]] = {}
    for task, steps in TASK_CHAINS.items():
        resolved = []
        for source, provider, model in steps:
            if source == "universal":
                runnable = bool(EMERGENT_LLM_KEY) and is_owner
                shown_model = model
            else:
                doc = all_byok.get(provider)
                cfg = await resolve_byok(user["user_id"], provider)
                runnable = bool(cfg)
                if provider == "ollama" and runnable and isinstance(cfg, dict):
                    shown_model = cfg.get("default_model", model)
                else:
                    shown_model = (doc or {}).get("preferred_model") or model
            if private_mode and provider != "ollama":
                runnable = False
            resolved.append({
                "source": source, "provider": provider, "model": shown_model,
                "runnable": runnable,
            })
        out[task] = resolved
    return {"chains": out, "private_mode": private_mode, "is_owner": is_owner}
