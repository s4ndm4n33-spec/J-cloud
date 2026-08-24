# Migration Log — Sovereign Shards · Gauntlet DevSpace

> Append-only build timeline for the Gauntlet DevSpace product itself
> (not user workspaces — those live at `.gauntlet/migration.log.md` inside
> each project). Every entry is code-signed and dated. Do not edit older
> entries; add a new one instead.

_initialized 2026-06-11T04:05:00+00:00 by **E1 (main agent)**_

---

## 2026-05-23T00:00:00+00:00 — v1.0 MVP — Sovereign Shards Cloud IDE
_signed: **E1 (main agent)**_  `mvp` `architecture`

**Problem.** User wanted to refine the `sovereign-shards/cloud` repo into a top-tier dev environment with an AI coworker that obeys the Five Masters Gauntlet.

**Fix.** Built FastAPI backend + React shell from scratch — Monaco editor with custom "sovereign" theme, xterm.js terminal with `INTEGRITY HALT` interlock, AI Coworker right panel (Chat/Refine/Gauntlet/Logs), Five Masters AST engine ported from upstream `core/fivemasters.py`, destructive-pattern scanner with password override, Emergent Google OAuth.

**Why.** Sovereign Shards brand demanded a command-center HUD aesthetic, not a generic dark dashboard. Build it once, right — cyan/orange/viridian palette, Exo 2 + JetBrains Mono, glassmorphic panels, deterministic motion (no bouncy springs).

**Next step.** Wire LLM failover chain.

---

## 2026-05-23T18:00:00+00:00 — LLM Failover Chain
_signed: **E1 (main agent)**_  `feature` `llm`

**Problem.** Emergent Universal Key budget exhausted mid-build; AI panel went dark. Single-provider LLM call was a single point of failure.

**Fix.** Implemented `_chain_call` — Universal Key runs first, then cascades through user BYO keys (same provider → cross-provider), 2 full passes, per-task chains for chat/refine/governance. Endpoint `GET /api/ai/chain` returns the resolved chain (ARMED/SKIP per step).

**Why.** Sovereign Infrastructure pillar — "if it can't prove integrity, it halts." Falling silent because one key was exhausted is the opposite of sovereign.

**Next step.** Surface chain telemetry visually.

---

## 2026-05-23T20:00:00+00:00 — Chain Telemetry Strip
_signed: **E1 (main agent)**_  `feature` `ui`

**Problem.** Failover happened invisibly — operators couldn't see which provider was actually answering.

**Fix.** Added bottom HUD strip showing last 5 LLM calls as instrument-panel pills (task glyph CHT/RFN/GNT · source/provider · latency ms · ↻N fallback count). Latest pill flashes 1px cyan stroke. Backed by `GET /api/ai/telemetry` + Mongo `llm_telemetry` collection populated by `_chain_call`.

**Why.** Verifiable Execution pillar — make the LLM behaviour visible like an aircraft cockpit.

**Next step.** Add GitHub integration.

---

## 2026-05-25T06:00:00+00:00 — Full GitHub Suite + 100-point Audit + Mobile
_signed: **E1 (main agent)**_  `feature` `github` `audit` `mobile`

**Problem.** No GitHub integration. No way to measure project quality. UI was unusable on phones.

**Fix.**
1. PAT-based GitHub: connect/disconnect, repo browser, clone, create+push, link, push, pull, open PR. Tokens encrypted at rest in the same Fernet vault as LLM keys.
2. Deterministic 100-point Project Audit: Five Masters AST 40 + destructive 15 + docs 10 + tests 10 + types 10 + hygiene 10 + deps 5. Grade S→F. **Opt-in refactor only — J proposes, user APPLYs.**
3. `.gauntletignore` seeded into new projects, respected by auditor.
4. File upload (multi), per-file download, full-project zip.
5. BYO agents API (`/api/agents`) + Fernet-encrypted endpoint keys.
6. Mobile shell < 900px: drawers + bottom dock (FILES / TERM / J).

**Why.** User asked for the full git suite (a–e) plus mobile fix. Audit rubric enforces Sovereign Shards philosophy without nagging.

**Next step.** Give J real tools so he can actually mutate files from chat.

---

## 2026-05-30T09:43:00+00:00 — Agentic Tooling — J Can Now Build Things
_signed: **E1 (main agent)**_  `feature` `agent` `tools`

**Problem.** J could TALK about files but couldn't TOUCH them. User: "HUGE freaking problem . J has no ability to really create folders or files when i tell him to."

**Fix.** Built `POST /api/ai/agent` ReAct-style tool-call loop. 20 tools across 6 categories — filesystem CRUD, search, run_command, git, github, gauntlet, audit, web_fetch, ask_user, done. Each tool call surfaces in chat as a collapsible card with args + result + OK/ERROR/BLOCKED badge. Safety rails: destructive scanner on `delete_file` and `run_command`, prompt requires `ask_user` before >5 mutations, path traversal hardened in every tool.

**Why.** Talking is not building. Verifiable Execution requires verifiable side effects.

**Next step.** Ingest large folders and zips reliably.

---

## 2026-05-30T18:23:00+00:00 — GitHub Panel Blank — Promise.all Trap
_signed: **E1 (main agent)**_  `bug` `frontend`

**Problem.** User: "The git icon does nothing." Production panel rendered blank. Root cause: `Promise.all([githubStatus(), gitStatus()])` — if either threw, neither piece of state was set, leaving the panel with default empty values.

**Fix.** Replaced `Promise.all` with sequential try/catch around each call so a single failure can't blank both. Wrapped panel in a React error boundary that shows a `RETRY` button instead of a void.

**Why.** Defensive coding (Hamilton). One I/O guard per call site, not one for the batch.

**Next step.** Large folder ingestion + zip builds.

---

## 2026-06-11T03:55:00+00:00 — Zip Ingestion + Auto-Build Tools
_signed: **E1 (main agent)**_  `feature` `tools`

**Problem.** User: "J has to be able to ingest large folders through the upload function and reliably build and compile from zip files." Existing `upload_file` was single-file; `run_command` timeout was 30s (too short for `npm install`); no project-type detection.

**Fix.**
1. `POST /api/projects/{id}/upload_zip` — extracts a `.zip` with auto-strip of single top-level folder (GitHub-style), 500MB total / 100MB per-file cap, junk-dir filter, path-traversal safe.
2. `POST /api/projects/{id}/upload_folder` — multi-file upload preserving relative paths from browser folder picker.
3. New J tools: `detect_project` (classifies node/python/rust/go/java/ruby/php/make/docker + suggested commands), `install_deps`, `build_project`, `extract_zip`.
4. `run_command` default timeout 30s → 120s, max 600s for long builds.
5. FileTree gained drag-drop ingestion with cyan overlay, folder picker, and percentage progress bar.

**Why.** Real dev work means real codebases. A "build environment" that can't unzip a project is a chat box with delusions of grandeur.

**Next step.** Auto migration logs.

---

## 2026-06-11T04:05:00+00:00 — Code-Signed Migration Log
_signed: **E1 (main agent)**_  `feature` `governance`

**Problem.** User: "add a migration log section that keeps build timelines listing the problems faced how and why they were fixed and what the next step should be in the build... when J creates them make sure they are signed and dated. If you could make the code do it instead of the llm that would be exquisite."

**Fix.** Built `core/migration_log.py` — append-only markdown at `.gauntlet/migration.log.md` inside each project workspace, written by deterministic Python code (zero LLM involvement, zero hallucination risk). Hooks: agent loop logs every milestone tool call (signed `J`), audit logs every run (signed `SYSTEM`), session starts get a marker, manual entries via `POST /api/projects/{id}/migration_log` signed with the user's name. New `GET /api/projects/{id}/migration_log` returns the rendered file. Each entry: ISO-8601 UTC timestamp + `_signed: **<who>**_` + tags + problem/fix/why/next-step + structured `extra` JSON block.

**Why.** Verifiable Execution — code-signed entries can be audited and trusted. LLM-generated logs can be elegant fiction; code-generated logs are receipts. Travels with the workspace (zip download, git push, etc.).

**Next step.** Surface the log in the UI as a new AI Coworker tab so users can read their own build history without curl. Add a "Pin entry" button so important milestones float above the auto-noise.

---

## 2026-08-24T02:40:00+00:00 — Prod Environment Alignment (Training Pipeline + BYOK Model Picker)
_signed: **E1 (main agent)**_  `feature` `training` `byok` `prod`

**Problem.** Three separate leaks between preview and production were quietly conspiring to poison the training loop and hide fluid model selection from users:
1. Training exporter (`export_sft` / `export_dpo`) read from whichever `db` the backend was bound to — in preview that's `mongodb://localhost:27017/test_database`, i.e. junk data. Any dataset built in preview was silently poisoned with test rows.
2. Bolt.new Training Console was documented to point at `blue-j-gauntlet.com` but there was no client-side lock — a single misclick in the Settings pane could re-route the whole pipeline at preview data.
3. `preferred_model` was fully honoured at the chain layer (`llm_chain.py:234-235`) and persisted correctly on `PUT /settings/keys`, but the SettingsModal only exposed a model picker for Ollama. Effectively dead code for OpenAI / Anthropic / Gemini / Groq / OpenRouter — non-owners were stuck on the hardcoded `TASK_CHAINS` defaults with no way to pin their own slug.

**Fix.**
1. `deps.py` now exposes `prod_db` — a dedicated motor client built from `PROD_MONGO_URL` + `PROD_DB_NAME`. Falls back to `db` when unset, zero regression. `routes/training.py::_run_export` reads from `prod_db` and stamps every dataset row with `source: "prod" | "preview"` so nobody accidentally trains on junk.
2. `docs/bolt-training-console-lock-prod.md` — paste-in prompt for the bolt.new console that (a) defaults `apiBaseUrl` to prod, (b) auto-heals any `preview.emergentagent.com` string found in localStorage, (c) alarms with a red banner if `data.public_backend_url` doesn't match the client's `apiBaseUrl`, (d) renders a `SOURCE · PROD | PREVIEW` chip under the health pills.
3. `routes/settings.py::set_key` — the `PUT /settings/keys` endpoint now accepts model-only updates when a key is already on file (no re-paste required). Empty `preferred_model` explicitly clears the override via `$unset`. `SettingsModal.jsx` renders a second row per BYOK provider with a text input + `MODEL` save button, placeholder-hinted from `MODEL_HINTS`. Seeds from the persisted `preferred_model` and disables the save button when unchanged.

**Why.** Sovereign Infrastructure — the training pipeline is downstream of every user turn. If it silently drinks from the wrong tap the whole fine-tune is compromised, and the receipts we produced would be false receipts. Fluid model picking is what makes the "J on OpenRouter → J failing over to J" dogfood loop possible: publish an adapter, paste its slug, zero code changes needed.

**Next step.** Add a matching `SOURCE · PROD | PREVIEW` chip inside the main Gauntlet DevSpace HUD so operators can never lose track of which environment they're typing into. Then upgrade the fluid text field to a live dropdown by fetching each provider's `/models` list on save.

**extra.**
```json
{
  "files_touched": [
    "backend/deps.py",
    "backend/routes/training.py",
    "backend/routes/settings.py",
    "backend/.env",
    "frontend/src/components/SettingsModal.jsx",
    "docs/bolt-training-console-lock-prod.md"
  ],
  "env_vars_added": ["PROD_MONGO_URL", "PROD_DB_NAME"],
  "endpoints_touched": ["PUT /api/settings/keys"],
  "dataset_row_schema_delta": {"source": "prod | preview"},
  "activation": "Paste read-only prod Mongo URI into PROD_MONGO_URL (in preview .env); restart backend."
}
```

---

## 2026-08-24T02:55:00+00:00 — Dual Owner Reconciliation + Ollama Context Guardrail (WKL Preserved)
_signed: **E1 (main agent)**_  `bugfix` `feature` `ollama` `wkl` `owner`

**Problem.** Two entangled failures on the metal machine:

1. **Dual `OWNER_USER_ID` unreconciled.** Owner has two `user_id`s (one from phone login, one from laptop). Chain owner-lock at `llm_chain.py` compared `user_id == OWNER_USER_ID` — a scalar string equality. Whichever `user_id` didn't match got treated as a non-owner: universal key stripped, forcing BYOK, and (per the RCA on the just-deployed prod) exhausting the whole 12-step chain when the BYOK keys stored in prod's Mongo were revoked/rate-limited copies. J had started a WIP fix in `llm_chain.py:237-244` — 8 lines of `isinstance(OWNER_USER_ID, str/bytes/list/set/tuple)` branch guessing — but abandoned it mid-flight when the context blew up. That WIP was still in the file, functional but only for the parse-CSV branch and confusingly typed.

2. **40k-token prompt hitting a 4096-token local model.** Running J on-metal via Ollama. Chat context concatenates the CHAT_PROMPT (~7 KB) + `_build_context_block` (open file body!) + J:MIND recall (5 facts × ~350 chars) + eidetic history (up to 50 prior turns × 2000 chars = 100 KB). The `_call_ollama` path had a **WKL (Weighted Key Language)** compression layer already wired — a bijective schema in `wkl_schema.json` that maps common substrate vocab (`" the "` → `"$00"`, `" gauntlet "` → `"$13"`, `" substrate "` → `"$12"`, etc.) into 3-char keys — but WKL alone yields only ~30–40% char savings, nowhere near enough to fit 40k into 4k. WKL was also **completely undocumented** outside this file: not in the migration log, not surfaced in the Settings UI, not mentioned in `AGENTS.md`.

**Fix.**
1. `deps.py` — `OWNER_USER_ID` env now parses as comma-separated → `OWNER_USER_IDS` frozenset. Kept legacy scalar `OWNER_USER_ID` bound to the first entry for backwards compat. Added `is_owner(uid: str) -> bool` helper. `get_current_user` injects `user["is_owner"]` once so every downstream route just checks `user.get("is_owner")` instead of re-parsing env.
2. Swept the four owner-gated route files (`ai.py`, `training.py`, `agent_tunnel.py`, `reports.py`) plus `auth.py::/auth/me` to consume `user.get("is_owner")` uniformly. Deleted J's abandoned 8-line `isinstance` branch in `llm_chain.py` and replaced with `is_owner = user_id in OWNER_USER_IDS`.
3. `_call_ollama` in `llm_chain.py` — hard char-budget trim **before** the WKL encode step. Head-preserves system prompt (≥2500 chars — persona identity), tail-preserves user_text (most recent turns + current message). Prepends `[…context truncated for local model — showing most recent…]` marker so J knows history was clipped. Default budget 14000 chars (~3500 input tokens, leaves 512 for response inside a 4096 window). Override via `OLLAMA_CHAR_BUDGET` env for tighter (2K) or wider (128K llama3.1) contexts. WKL preserved intact — now runs on the already-trimmed text, so the two layers stack (~40k → 14k trim → ~9k on the wire).
4. Verified WKL bijectivity by running the module self-test: `"the gauntlet backend and the substrate protocol"` → `"the$13backend$01the$12protocol"` → decodes losslessly (37% savings on that sample).

**Why.** Sovereign Infrastructure — owner-lock is the whole reason preview and prod are separate. A silent classification mistake ("you're not the owner") strips the universal fallback and pushes every call onto BYOK, which is exactly what took prod dark this week. And Verifiable Execution — a local model that silently overflows and rejects the request is worse than one that refuses to start; the trim + marker makes the constraint legible to J instead of being an invisible ceiling.

**Next step.** Add an `OLLAMA_CHAR_BUDGET` control in the Settings modal (currently env-only) so users can tune it per-model without a restart. Ship WKL v2 — dynamically pad the schema with each user's project-specific vocab (extracted from the top-N tokens in their chronicle) for another ~15% compression. Add an `LLM Exception Categorizer` (already scoped in PRD) so opaque `chain exhausted` messages become an at-a-glance provider health board.

**extra.**
```json
{
  "files_touched": [
    "backend/deps.py",
    "backend/llm_chain.py",
    "backend/routes/ai.py",
    "backend/routes/training.py",
    "backend/routes/agent_tunnel.py",
    "backend/routes/reports.py",
    "backend/routes/auth.py"
  ],
  "env_vars_new": ["OLLAMA_CHAR_BUDGET (optional, default 14000)"],
  "env_vars_semantics_changed": ["OWNER_USER_ID (now comma-separated list, backwards compatible)"],
  "wkl": {
    "location": "backend/wkl_transformer.py + backend/wkl_schema.json",
    "activation": "loaded automatically when wkl_schema.json exists; applied only in _call_ollama",
    "roundtrip_verified": true,
    "sample_savings_pct": 37
  },
  "things_i_found_that_were_previously_missed_or_messed_up": [
    "J's WIP dual-owner isinstance branch in llm_chain.py (dead code / stale mid-refactor) — removed.",
    "WKLTransformer + wkl_schema.json shipped but zero documentation in MIGRATION_LOG, AGENTS.md, or the Settings UI — logged here now.",
    "preferred_model fully wired at the DB/chain layer but no UI exposure for cloud providers — fixed in the prior entry.",
    "Zero users with is_owner=true in prod Mongo per deployer RCA — the new OWNER_USER_IDS pathway bypasses the DB flag entirely and computes membership from env, which is what the code always intended.",
    "Preview and prod are on SEPARATE Mongos — BYOK keys saved in preview NEVER propagate to prod. Not a bug, but an operator invariant that was undocumented. Documented via the SOURCE chip in the prior entry."
  ]
}
```

---

