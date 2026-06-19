# Gauntlet DevSpace — PRD

> DETERMINISTIC. AUTONOMOUS. SUBSTRATE.

## Original problem statement
> "https://github.com/s4ndm4n33-spec/sovereign-shards/tree/main/cloud — this is the product, and the brand. I need you to refine the project by making it more robust and function as a top tier development environment for users. Fully integrated AI coworker not only in chat box but as an editing and code refinement system following the AST governance standards of the Five Masters Gauntlet."

## User choices (verbatim)
- Clone the repo and refine the existing code into a top-tier dev environment inspired by the brand / playbook / `fivemasters.py`.
- LLMs (Emergent Universal Key): **Claude Sonnet 4.5** for Five Masters governance, **Gemini** for chat, **GPT-5.2** for refinement.
- Core IDE: Monaco + file tree + multi-tab, integrated terminal, AI chat panel with project context, inline AI edit/refactor (Cmd+K) with Five Masters AST review, git integration, live preview pane.
- Enforcement: HARD BLOCK on destructive code with explicit password-guarded override.
- Auth: Emergent Managed Google OAuth.

## Architecture
- **Frontend (React, /app/frontend)**: Sovereign Shards branded shell (Exo 2 + JetBrains Mono + IBM Plex Sans). Monaco editor with a custom "sovereign" dark theme; xterm.js terminal; AI Coworker panel with four tabs (Chat / Refine / Gauntlet / Logs).
- **Backend (FastAPI, /app/backend)**: REST API behind `/api` prefix on port 8001. MongoDB for users / sessions / projects / messages / overrides. Workspaces on disk at `/app/workspaces/{user_id}/{project_id}` (self-healing — re-seeds if disk dir is missing but DB entry exists).
- **Five Masters AST engine** (`core/fivemasters.py`): deterministic AST evaluator, ported from `s4ndm4n33-spec/sovereign-shards/core/fivemasters.py`. Heuristic fallback for non-Python languages.
- **Destructive interlock** (`core/destructive.py`): regex bank for 18+ destructive patterns (`rm -rf /`, fork bombs, `mkfs`, `dd if=...of=/dev/`, raw `DROP DATABASE`, `git push --force main`, `shutil.rmtree`, etc.). Critical matches HARD-BLOCK terminal exec with HTTP 423 until a consume-once override token is obtained via password.
- **J persona** (`core/persona.py`): the B.L.U.E.-J. directive — witty, sardonic, kind, capable. Injected as system prompt into every LLM call (chat/refine/governance).

## Implemented (2026-05-23)
- **LLM Failover Chain** — Universal Key always runs first as primary. If it fails (budget, rate-limit, model down), J automatically cascades through the user's BYO keys: same provider first, then cross-provider, until one succeeds. Per-task chains:
  - **Chat**: Universal/gemini-3-flash → BYO gemini-3-flash → BYO openai gpt-5.4-mini → BYO anthropic claude-haiku-4.5
  - **Refine**: Universal/gpt-5.2 → BYO openai gpt-5.2 → BYO anthropic claude-sonnet-4.5 → BYO gemini-3-flash
  - **Governance**: Universal/claude-sonnet-4.5 → BYO anthropic claude-sonnet-4.5 → BYO openai gpt-5.4 → BYO gemini-3.1-pro
  - 2 full passes before declaring offline. Every attempt logged in response `meta.attempts`. Endpoint `GET /api/ai/chain` returns the resolved chain (ARMED/SKIP per step). The AI Coworker chat bubbles show "via universal/gemini" badges (and "· 2 fallbacks" when the chain had to step through).
- **BYO-Key Settings panel** — Top-bar gear icon opens a modal where users paste their own OpenAI / Anthropic / Gemini keys. Keys encrypted at rest with Fernet (`core/keyvault.py`), masked in UI. Modal shows the **RESOLVED CHAIN** section listing every step per task with ARMED/SKIP status. Endpoints: `GET/PUT/DELETE /api/settings/keys`.
- Emergent Google OAuth (`/api/auth/session`, `/api/auth/me`, `/api/auth/logout`) with httpOnly cookies + Bearer fallback.
- Projects: list/create with auto-seeded `README.md`, `main.py`, `index.html`, `.gitignore` + `git init`.
- File CRUD (path-traversal guarded), tree walk excluding `.git`/`node_modules`/`__pycache__`/`.venv`.
- Five Masters AST eval `/api/gauntlet/evaluate` (Python AST + JS/TS heuristic).
- Destructive scan `/api/governance/scan` and password-guarded override `/api/governance/override` (consume-once 120s tokens, logged).
- Sandboxed terminal exec `/api/terminal/exec` with HARD BLOCK + override token plumbing.
- Git integration: status / commit / log.
- AI Coworker:
  - **Chat (Gemini 3 Flash)** with full project context (open file + tree summary). Graceful `// J:OFFLINE` fallback when LLM budget is exhausted.
  - **Refine (GPT-5.2)** Cmd+K inline edit with auto Five-Masters AST badge on output + destructive scan.
  - **Gauntlet (Claude Sonnet 4.5)** structured-JSON verdict (PASS / FAIL + per-master notes + fixes). AST-only fallback if LLM down.
- Frontend:
  - Sovereign Shards sign-in landing (HUD frame, brand pillars, "DEPLOY THE SHARD").
  - Top bar with Gauntlet HUD (5-dot indicator), project switcher, Preview toggle, user/avatar/logout.
  - Left rail (Files / Git / Gauntlet) + file tree (iterative flatten — avoids visual-edits Babel recursion bug).
  - Monaco editor with custom "sovereign" theme + multi-tab bar (per-tab Five Masters score badge + dirty dot).
  - xterm terminal with cyan prompt, INTEGRITY HALT detection.
  - AI Coworker right panel: Chat (textarea+stream), Refine, Gauntlet (Quick AST + Full Gauntlet verdict), Logs.
  - Inline Edit modal (Cmd+K) — 2-stage flow: instruction → diff preview + Gauntlet verdict → apply.
  - HARD BLOCK modal — amber/orange INTEGRITY HALT with password input.
  - Live Preview pane — slide-in iframe of `index.html`, desktop / mobile toggle.
  - Git Panel with branch, changes, commit, log.

## Testing
- 65/65 backend pytest tests pass as of iter4 (`/app/backend/tests/`).
- iter3: Bearer-token + localStorage auth fallback for mobile (45/45 + 7/7 frontend).
- iter4: Ollama BYOK + Tutorial overlay + Bearer-only logout fix (20/20 new + 45/45 regression = 65/65 + frontend Tutorial/Settings flows).
- Frontend smoke: sign-in landing renders, IDE shell loads, file open works, single-tab dedupe verified, Gauntlet HUD updates, Tutorial auto-launches with 8-step spotlight tour.

## Test credentials
See `/app/memory/test_credentials.md`.

## Recently implemented (2026-06-18 → 2026-06-19)
- **PTY-backed WebSocket terminal (2026-06-19)**: `/api/terminal/ws` spawns a real bash via `pty.fork()` per WS connection. Fixes everything the user called out — `cd`/`export`/aliases persist, Python/node REPLs + vim/less/top work, output streams byte-by-byte, ANSI colors interpreted, arrow-key history + tab completion handled by bash readline. No artificial timeout on the WS shell. The HTTP `/api/terminal/exec` (used by J's agent tool) timeout bumped 30s → 300s and still routes through the destructive scanner + password-override flow.
- **In-shell destructive trap**: bash DEBUG trap with `extdebug` + `shopt -s extdebug` refuses `rm -rf /|~|/*|.|..`, `mkfs.*`, `dd of=/dev/{sd,nvme,hd,mmc}*`, fork bombs, and `chmod -R 777 /` directly inside the shell — no UI roundtrip needed. Depth-guard (`${#FUNCNAME[@]} -gt 1` returns early) ensures the trap only fires on top-level interactive commands, not on helper functions. `j-help` command prints a full color-coded reference inside the shell.
- **J system-prompt addendum**: `core/terminal_reference.md` is loaded into the agent system prompt on every turn so J knows exactly what the terminal can/can't do — including which path (WS vs HTTP exec) corresponds to which tool, the 300s HTTP cap, that `cd` doesn't persist across `run_command` calls, and a recipe cookbook. Reduces hallucinations.
- **Per-user shell cap**: 5 concurrent WS shells per user; the 6th gets a clear error frame and close code 4429.
- **Content-addressed rcfile**: `/tmp/j_devspace_bashrc_<sha8>` ensures BASHRC edits propagate without manual cleanup.
- **Private Mode toggle (2026-06-19)**: One-click `PUBLIC ↔ PRIVATE` pill in the TopBar (Lock/LockOpen icon, cyan glow when active). When PRIVATE, the chain filter inside `_chain_call` strips every non-ollama step, so neither the Universal Key nor any cloud BYOK is ever touched. New endpoints `GET/POST /api/me/private-mode`; backend refuses to enable when no local server is linked (400 with a clear message). `GET /api/ai/chain` now returns a top-level `private_mode` bool and reports every cloud step as `runnable:false` when on — so the Settings Resolved-Chain panel updates live. Tutorial gained a 9th step explaining the toggle. 76/76 backend tests + full frontend Playwright flow pass.
- **Mobile Android OAuth fix**: `/api/auth/session` now returns the `session_token` in JSON body in addition to the `Set-Cookie`. `api.js` stores it in `localStorage` (`gauntlet_session_token`) and an axios request interceptor attaches `Authorization: Bearer <token>` on every request. `get_current_user` falls back to the Bearer header when the cookie is absent. `AuthCallback` now uses `window.location.replace('/ide')` (hard navigate) to avoid the React state race; it also extracts `session_id` from both URL hash AND query string. Closes the infinite-redirect loop on Android Chrome (which blocks third-party cookies on cross-origin OAuth bounces).
- **Bearer-only logout invalidation**: `/api/auth/logout` now accepts Authorization header and deletes the `user_sessions` row by whichever token is present. No more zombie sessions when mobile users sign out.
- **Mobile UI polish**: removed `pr-28` clipping on the bottom dock so the `J` button reaches the right edge; AI drawer is now `w-screen max-w-md`.
- **Ollama / llama.cpp local-server BYOK** (first-class 4th provider): SUPPORTED_PROVIDERS = ('openai', 'anthropic', 'gemini', 'ollama'). Stored as `base_url` + `default_model` (no API key). `_call_ollama` uses `openai.AsyncOpenAI` against `{base_url}/v1` — works for Ollama, llama.cpp-server, and vLLM out of the box. New endpoint `POST /api/settings/keys/ollama/test` smoke-pings `/api/tags` then falls back to `/v1/models` so users see CONNECTED/OFFLINE instead of guessing. Ollama is appended as the LAST step in every TASK_CHAIN (chat/refine/governance) — only runs when Universal Key + cloud BYOK are exhausted or absent.
- **Settings UX**: SettingsModal now has a dedicated Ollama section with preset chips (ollama → :11434, llama-cpp → :8080), URL + model fields, TEST CONNECTION button (green CONNECTED / orange OFFLINE pill with model list), LINK SERVER button. Resolved-chain panel renders 5 steps per task with ARMED/SKIP gating including the new Ollama row.
- **Interactive Tutorial**: 8-step coachmark overlay (`Tutorial.jsx`) with spotlight cutout, target-element highlight ring, progress bar, NEXT/BACK/SKIP/GO BUILD controls. Auto-launches on first `/ide` load (server flag `users.tutorial_completed`). Always-available `?` replay button in the TopBar. Steps: Welcome → Top Bar → Project switcher → File Tree → Monaco → AI Coworker → Settings (BYOK/Universal/Ollama explained) → "Go build". Endpoints: `GET/POST /api/me/tutorial`.

## Backlog / P1
- Multi-cursor inline-diff editor for InlineEditModal output (currently full-block replace).
- File rename / drag-and-drop in tree.
- Git: branch creation/switch UI, push to remote (PAT works; full OAuth pending user credentials).
- Per-master deterministic auto-fix (port the 8 AST transforms from upstream `app/agent/transforms.py`).
- Workspace persistence beyond preview pod lifetime (MongoDB GridFS or S3-compatible storage).

## P2
- Terminal: PTY-backed streaming session via WebSocket (currently request-response).
- Live Preview: dev-server proxy for SPA projects.
- Five Masters language pack: native AST analyzers for JS/TS/Rust/Go.
- Refactor: split `server.py` (1766 lines) into `/app/backend/routes/{auth,keys,ai,projects,github,tutorial,audit}.py`.

## Next Action Items
1. Push fixes live: hit **Deploy** to roll the mobile-OAuth fix + Ollama support + Tutorial out to blue-j-gauntlet.com.
2. Optional: pull a small model (`ollama pull llama3.1`) on a private host to validate the local-server failover end-to-end.
3. Optional: top up Emergent Universal Key (Profile → Universal Key → Add Balance) if the budget is exhausted.
