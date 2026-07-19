"""LLM failover chain — Universal Key → BYOK (cloud) → BYOK (other cloud) → Ollama.

Centralizes:
- TASK_CHAINS (chat / refine / governance)
- resolve_byok (cloud + ollama config)
- Ollama / OpenAI-compat local server caller
- The actual chain_call orchestrator with Private Mode filtering and telemetry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from deps import db, log, EMERGENT_LLM_KEY, OWNER_USER_ID
from core.keyvault import decrypt_key

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
    if not base.endswith("/v1"):
        base = base + "/v1"
    client_ai = AsyncOpenAI(api_key="local", base_url=base, timeout=120.0)
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

    # OWNER LOCK: the shared EMERGENT_LLM_KEY is only usable by the app owner.
    # Every non-owner MUST bring their own key (BYOK / Ollama). We simply drop
    # the universal steps from the chain for non-owners so the failover logic
    # naturally cascades to their BYOK steps. If they have none configured,
    # the chain will end with `success=False` and meta.needs_keys=True.
    is_owner = bool(OWNER_USER_ID) and user_id == OWNER_USER_ID
    if not is_owner:
        chain = [s for s in chain if s[0] != "universal"]

    attempts: list[dict] = []
    chain_started = _time.perf_counter()

    for pass_idx in range(max_passes):
        for source, provider, model in chain:
            if source == "universal":
                api_key = EMERGENT_LLM_KEY
            else:
                api_key = await resolve_byok(user_id, provider)
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
    # Signal to the caller (and the frontend) whether this user still needs
    # to bring their own key. True when every remaining step was skipped
    # because BYOK was missing (i.e. non-owner with no cloud key + no ollama).
    if attempts and all(a.get("status") == "skipped" and a.get("reason") == "byok-missing"
                        for a in attempts):
        meta["needs_keys"] = True
    elif not attempts and not is_owner:
        # Chain was empty after owner-lock (universal stripped, no BYOK) —
        # nothing was even attempted.
        meta["needs_keys"] = True
    await _record_telemetry(user_id, meta)
    return "", meta
