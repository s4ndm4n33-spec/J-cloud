# Feature Spec — Add Groq + OpenRouter to the BYOK Chain

> Handoff to Substrate J for implementation.
> Produce full files. Send back for main-agent review before merge.
> No scope creep — this spec is the entire scope.

---

## Goal

Give public users two additional BYOK providers so their `chat/refine/governance` chain is 6 steps deep instead of 4, with genuine resilience against any single provider being deprecated.

- **Groq** — free tier, no credit card, ~10× faster than GPT via LPU chips
- **OpenRouter** — one key = 300+ models, insulates users from any single upstream EOL

Both use OpenAI-compatible chat completion APIs (same request/response shape as `openai` SDK), so no new dependencies — reuse the existing `openai.AsyncOpenAI` client with different `base_url`.

Owner (`OWNER_USER_ID`) is exempt from BYOK for these too — universal steps are unchanged.

---

## Files to touch (5 total)

### 1. `/app/backend/llm_chain.py` (MODIFY)

**Rules:**
- Do NOT change the `universal` steps of any task chain.
- Do NOT rename or remove existing providers.
- New byok steps go AFTER the current 4 BYOK steps in each chain, in this order: `groq` first, `openrouter` second, then `ollama` LAST (so local runs last resort).

**Changes:**

a) Extend `TASK_CHAINS` — add `groq` and `openrouter` steps to all three tasks. Final order per task:

```python
TASK_CHAINS = {
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
```

b) Extend `_single_call()` to route `groq` and `openrouter` through an OpenAI-compat handler:

```python
_OAI_COMPAT_BASE_URLS = {
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

async def _call_oai_compat(base_url: str, api_key: str, model: str,
                           system: str, user_text: str) -> str:
    """Call any OpenAI-compatible provider (Groq, OpenRouter, others)."""
    from openai import AsyncOpenAI
    client_ai = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90.0)
    resp = await client_ai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text},
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content or ""
```

Then in the existing `_single_call` provider-dispatch block, before the `emergentintegrations` fallback:

```python
if provider in _OAI_COMPAT_BASE_URLS:
    return await _call_oai_compat(
        _OAI_COMPAT_BASE_URLS[provider],
        api_key_or_cfg,
        model, system, user_text,
    )
```

c) `resolve_byok(user_id, provider)` — no change. It already reads by provider name from `user_provider_keys`. The new provider names just work.

d) Update the module docstring's provider list to include `groq` and `openrouter`.

### 2. `/app/backend/routes/settings.py` (MODIFY)

**Rules:**
- Do NOT touch existing provider validators.
- Add a case in `validate_key` for both new providers that does a real live `/v1/models` HTTP call so bad keys fail fast at save time.

**Changes:**

a) In `validate_key()`, add branches:

```python
elif provider == "groq":
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as ac:
        r = await ac.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="Invalid Groq API key")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Groq returned {r.status_code}")
    models = [m["id"] for m in r.json().get("data", [])][:20]

elif provider == "openrouter":
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as ac:
        r = await ac.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="Invalid OpenRouter API key")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"OpenRouter returned {r.status_code}")
    # OpenRouter returns hundreds — surface a curated shortlist rather than all.
    all_ids = [m["id"] for m in r.json().get("data", [])]
    preferred_prefixes = ("anthropic/", "openai/", "google/", "meta-llama/",
                          "mistralai/", "deepseek/", "qwen/")
    models = [m for m in all_ids if m.startswith(preferred_prefixes)][:30]
```

Return shape same as existing providers: `{"ok": True, "provider": provider, "models": models, "masked": mask(api_key)}`.

b) If there's a `VALID_PROVIDERS` set/list anywhere in this file that enumerates allowed provider names for POST/PUT/DELETE endpoints, add `"groq"` and `"openrouter"` to it.

### 3. `/app/backend/deps.py` (VERIFY, likely NO CHANGE)

Confirm nothing hardcodes the list of provider names such that adding a new one would break existing routes. If a `PROVIDERS = ("openai","anthropic","gemini","ollama")` tuple exists, extend it to include the two new names. Otherwise leave alone.

### 4. `/app/frontend/src/components/BYOKInlineCard.jsx` (MODIFY)

**Rules:**
- Preserve the existing dark/cyan aesthetic. Match the exact card style used for OpenAI/Anthropic/Gemini.
- Both new tiles use `<input type="password">` for the key.
- Every interactive element MUST have a `data-testid` following the existing kebab-case pattern.
- Both new tiles should show a "sign up (free)" link that opens in a new tab.

**Add two new provider tiles below the existing four:**

```
Groq
  - label: "Groq (fast + free tier)"
  - placeholder: "gsk_..."
  - signup URL: https://console.groq.com/keys
  - data-testids: byok-groq-input, byok-groq-save, byok-groq-signup, byok-groq-status
  - default model displayed: llama-3.3-70b-versatile

OpenRouter
  - label: "OpenRouter (300+ models via one key)"
  - placeholder: "sk-or-v1-..."
  - signup URL: https://openrouter.ai/keys
  - data-testids: byok-openrouter-input, byok-openrouter-save, byok-openrouter-signup, byok-openrouter-status
  - default model displayed: meta-llama/llama-3.3-70b-instruct
```

Save handler reuses the existing `saveProviderKey(provider, api_key)` and `validateProviderKey(provider, api_key)` API helpers — no new frontend API functions needed. If those helpers hardcode the accepted provider list, extend them.

### 5. `/app/frontend/src/pages/Settings.jsx` (MODIFY, if a full Settings page exists)

**Rules:**
- If Settings has a full BYOK section (not just the inline card), mirror the two new tiles there.
- If Settings only imports `BYOKInlineCard`, no change needed.
- Preserve existing preferred-model dropdown pattern — for each new provider, allow the user to override the default model (Groq: user might prefer `llama-3.1-8b-instant` for speed; OpenRouter: user might prefer `anthropic/claude-sonnet-4.5` for quality).

---

## What NOT to touch

- `core/persona.py`, `core/agent_prompt.py`, `core/tools.py` — no persona changes
- `core/guardrails.py` — same substrate-secrecy behavior applies to all providers
- Any training/Modal code — unrelated to this feature
- `user_provider_keys` collection schema — no migration needed (keyed by `provider` string, new names just work)
- Rate limits — unchanged
- Environment variables — none added
- Package dependencies — the `openai` SDK is already installed and handles both new providers

---

## Ground truth references (read these BEFORE writing)

- `/app/backend/llm_chain.py` lines 74–140 (`TASK_CHAINS`, `_call_ollama`, `_single_call`)
- `/app/backend/routes/settings.py` lines 50–160 (`validate_key`, save, list, delete)
- `/app/backend/routes/settings.py` line 11 imports for `resolve_byok` and `valid_local_url`
- `/app/frontend/src/components/BYOKInlineCard.jsx` — full file for existing tile layout

---

## Acceptance criteria (test before returning)

1. `POST /api/settings/keys/validate` with `provider=groq` and a real Groq key returns 200 with a `models` list.
2. Same with an invalid Groq key returns 400 "Invalid Groq API key".
3. Same for `openrouter`.
4. `POST /api/settings/keys` with the two new providers saves the key.
5. `GET /api/settings/keys` lists all providers including the two new ones with masked keys.
6. `DELETE /api/settings/keys/groq` removes the key.
7. A non-owner user with ONLY a Groq key configured can successfully complete a `POST /api/ai/chat` request — chain skips missing providers, lands on Groq.
8. Backend lint clean: `ruff check /app/backend/` passes.
9. Frontend lint clean: eslint reports no NEW errors (existing eslint-disable warnings are pre-existing).
10. Rendered BYOK card in the app shows all 6 provider tiles in a clean grid with no overflow.

---

## Reporting back

When done, send back:
1. Full contents of every file you touched
2. Which of the 10 acceptance criteria you personally verified vs. which need main-agent verification
3. Anything unexpected you found in the existing code (bugs, dead code, TODOs)
4. Any deviation from the spec, with justification

Do NOT deploy. Main agent reviews the diff before merge to preview.
