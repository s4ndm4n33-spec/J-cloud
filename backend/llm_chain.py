"""LLM failover chain — Universal Key → BYOK (cloud) → BYOK (other cloud) → Ollama.

Centralizes:
- TASK_CHAINS (chat / refine / governance)
- resolve_byok (cloud + ollama config)
- Ollama / OpenAI-compat local server caller
- The actual chain_call orchestrator with Private Mode filtering and telemetry.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from openai import AsyncOpenAI  # used by Ollama + all OAI-compat providers (Groq, OpenRouter)

from deps import db, log, EMERGENT_LLM_KEY, OWNER_USER_IDS
from core.keyvault import decrypt_key

# Safe import for WKLTransformer (handles both package and root backend pathing)
try:
    from .wkl_transformer import WKLTransformer
except ImportError:
    from wkl_transformer import WKLTransformer

# Lazy or safe init for WKL
WKL_SCHEMA_PATH = os.environ.get("WKL_SCHEMA_PATH", "/app/backend/wkl_schema.json")
try:
    wkl = WKLTransformer(WKL_SCHEMA_PATH) if os.path.exists(WKL_SCHEMA_PATH) else None
except Exception as e:
    log.warning(f"WKLTransformer initialization skipped: {e}")
    wkl = None

OLLAMA_PRESETS = {
    "ollama":     "http://localhost:11434",
    "llama-cpp":  "http://localhost:8080",
}


def valid_local_url(url: str) -> bool:
    """Accept http(s)://host[:port] — keep it permissive but reject obvious junk."""
    if not isinstance(url, str):
        return False
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    if " " in u or len(u) > 256:
        return False
    return True


async def resolve_byok(user_id: str, provider: str) -> Optional[Any]:
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


async def _byok_meta(user_id: str, provider: str) -> dict:
    """Return {preferred_model} for a stored BYOK, or empty dict."""
    doc = await db.user_provider_keys.find_one(
        {"user_id": user_id, "provider": provider},
        {"_id": 0, "preferred_model": 1},
    )
    return doc or {}


# Task chains: Universal first, then BYO of preferred provider, then BYO of others.
# Each step: (source, provider, model). source = "universal" or "byok".
# Ollama model "user-default" means: use whatever default_model the user saved.
TASK_CHAINS: dict[str, list[tuple[str, str, str]]] = {
    "chat": [
        ("universal", "gemini",     "gemini-3-flash-preview"),
        ("byok",      "gemini",     "gemini-3-flash-preview"),
        ("byok",      "openai",     "gpt-5.4-mini"),
        ("byok",      "anthropic",  "claude-haiku-4-5-20251001"),
        ("byok",      "groq",       "llama-3.3-70b-versatile"),
        ("byok",      "openrouter", "meta-llama/llama-3.3-70b-instruct"),
        ("byok",      "ollama",     "user-default"),
    ],
    "refine": [
        ("universal", "openai",     "gpt-5.2"),
        ("byok",      "openai",     "gpt-5.2"),
        ("byok",      "anthropic",  "claude-sonnet-4-5-20250929"),
        ("byok",      "gemini",     "gemini-3-flash-preview"),
        ("byok",      "groq",       "llama-3.3-70b-versatile"),
        ("byok",      "openrouter", "anthropic/claude-sonnet-4"),
        ("byok",      "ollama",     "user-default"),
    ],
    "governance": [
        ("universal", "anthropic",  "claude-sonnet-4-5-20250929"),
        ("byok",      "anthropic",  "claude-sonnet-4-5-20250929"),
        ("byok",      "openai",     "gpt-5.4"),
        ("byok",      "gemini",     "gemini-3.1-pro-preview"),
        ("byok",      "groq",       "llama-3.3-70b-versatile"),
        ("byok",      "openrouter", "anthropic/claude-sonnet-4"),
        ("byok",      "ollama",     "user-default"),
    ],
}


# OpenAI-compatible providers — same request/response shape as `openai` SDK,
# just a different base_url. Groq (LPU-accelerated), OpenRouter (300+ upstreams),
# and anything else compat we add later go here.
_OAI_COMPAT_BASE_URLS = {
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


async def _call_oai_compat(base_url: str, api_key: str, model: str,
                           system: str, user_text: str) -> str:
    """Call any OpenAI-compat provider (Groq, OpenRouter, ...)."""
    client_ai = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90.0)
    
    # WKL Handshake (encode if available)
    if wkl:
        system += "\n\nYou are now communicating via the Weighted Key Language (WKL). Use the provided schema for all technical and frequent terms."
        system = wkl.encode(system)
        user_text = wkl.encode(user_text)

    resp = await client_ai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text},
        ],
        temperature=0.4,
    )
    raw_reply = resp.choices[0].message.content or ""
    return wkl.decode(raw_reply) if wkl else raw_reply


async def _call_ollama(base_url: str, model: str, system: str, user_text: str) -> str:
    """Call an OpenAI-compatible local server (Ollama, llama.cpp, vLLM).

    Local models often ship with a tight default context window (Ollama's
    default is 2K; most quantized llama.cpp builds cap at 4K). We do two
    layers of shrinking BEFORE the request:
      1. Hard char-budget trim — head-keep the system prompt (identity
         + protocol), tail-keep user_text (most recent turns + current msg).
      2. WKL encode — bijective token→key substitution of high-frequency
         substrate vocabulary. Decoded on the response so J still speaks
         English out.
    """
    # ~4 chars/token English; reserve 512 tokens of response headroom.
    # 3500 input tokens ≈ 14000 chars total pre-WKL.
    _CTX_CHAR_BUDGET = int(os.environ.get("OLLAMA_CHAR_BUDGET", "12000"))
    if len(system) + len(user_text) > _CTX_CHAR_BUDGET:
        sys_budget = min(len(system), max(2500, _CTX_CHAR_BUDGET // 3))
        user_budget = _CTX_CHAR_BUDGET - sys_budget - 200
        system = system[:sys_budget]
        if len(user_text) > user_budget:
            user_text = ("[…context truncated for local model — showing most recent…]\n"
                         + user_text[-user_budget:])

    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    client_ai = AsyncOpenAI(api_key="local", base_url=base, timeout=300.0)

    # WKL Handshake (encode if available)
    if wkl:
        system += "\n\nYou are now communicating via the Weighted Key Language (WKL). Use the provided schema for all technical and frequent terms."
        system = wkl.encode(system)
        user_text = wkl.encode(user_text)

    resp = await client_ai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text},
        ],
        temperature=0.4,
    )
    raw_reply = resp.choices[0].message.content or ""
    return wkl.decode(raw_reply) if wkl else raw_reply


async def _single_call(api_key_or_cfg: Any, provider: str, model: str,
                       system: str, user_text: str, session_id: str) -> str:
    if provider == "ollama":
        cfg = api_key_or_cfg if isinstance(api_key_or_cfg, dict) else {}
        chosen_model = model if model != "user-default" else cfg.get("default_model", "")
        if not chosen_model:
            raise RuntimeError("Ollama default model not configured")
        return await _call_ollama(cfg["base_url"], chosen_model, system, user_text)

    # OpenAI-compat providers (Groq, OpenRouter)
    if provider in _OAI_COMPAT_BASE_URLS:
        return await _call_oai_compat(
            _OAI_COMPAT_BASE_URLS[provider],
            api_key_or_cfg, model, system, user_text,
        )

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=api_key_or_cfg,
        session_id=session_id,
        system_message=system,
    ).with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=user_text))
    return resp if isinstance(resp, str) else str(resp)


async def _record_telemetry(user_id: str, meta: dict) -> None:
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


async def chain_call(user_id: str, task: str, system: str, user_text: str,
                     session_id: str, max_passes: int = 2
                     ) -> tuple[str, dict]:
    """Run the LLM call through the failover chain. Returns (reply, metadata)."""
    import time as _time
    chain = TASK_CHAINS.get(task, TASK_CHAINS["chat"])

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0, "private_mode": 1})
    private_mode = bool(user_doc and user_doc.get("private_mode"))
    if private_mode:
        chain = [s for s in chain if s[1] == "ollama"]

    # OWNER LOCK: the shared EMERGENT_LLM_KEY is only usable by the app owner(s).
    # OWNER_USER_IDS is a frozenset built from a comma-separated env var so a
    # single user with multiple accounts (phone + laptop) is recognized on both.
    is_owner = user_id in OWNER_USER_IDS
    if not is_owner:
        chain = [s for s in chain if s[0] != "universal"]

    attempts: list[dict] = []
    chain_started = _time.perf_counter()

    for pass_idx in range(max_passes):
        for source, provider, model in chain:
            if source == "universal":
                api_key = EMERGENT_LLM_KEY
                effective_model = model
            else:
                api_key = await resolve_byok(user_id, provider)
                if not api_key:
                    attempts.append({"pass": pass_idx, "source": source,
                                     "provider": provider, "model": model,
                                     "status": "skipped", "reason": "byok-missing",
                                     "ms": 0})
                    continue
                meta_doc = await _byok_meta(user_id, provider)
                effective_model = meta_doc.get("preferred_model") or model
            t0 = _time.perf_counter()
            try:
                reply = await _single_call(
                    api_key, provider, effective_model, system, user_text,
                    f"{session_id}-{source}-{provider}",
                )
                ms = int((_time.perf_counter() - t0) * 1000)
                attempts.append({"pass": pass_idx, "source": source,
                                 "provider": provider, "model": effective_model,
                                 "status": "ok", "ms": ms})
                meta = {
                    "success": True,
                    "step_used": {"source": source, "provider": provider, "model": effective_model},
                    "attempts": attempts,
                    "total_ms": int((_time.perf_counter() - chain_started) * 1000),
                    "task": task,
                }
                await _record_telemetry(user_id, meta)
                return reply, meta
            except Exception as e:  # noqa: BLE001
                ms = int((_time.perf_counter() - t0) * 1000)
                short = str(e)[:280]
                log.warning(f"chain[{task}] {source}/{provider}/{effective_model} failed in {ms}ms: {short}")
                attempts.append({"pass": pass_idx, "source": source,
                                 "provider": provider, "model": effective_model,
                                 "status": "error", "reason": short, "ms": ms})
                continue
    meta = {
        "success": False, "step_used": None, "attempts": attempts,
        "total_ms": int((_time.perf_counter() - chain_started) * 1000),
        "task": task,
    }
    if attempts and all(a.get("status") == "skipped" and a.get("reason") == "byok-missing"
                        for a in attempts):
        meta["needs_keys"] = True
    elif not attempts and not is_owner:
        meta["needs_keys"] = True
    await _record_telemetry(user_id, meta)
    return "", meta