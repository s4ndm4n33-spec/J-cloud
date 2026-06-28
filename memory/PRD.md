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

## Recently implemented (latest first)
- **CHRONICLE HYGIENE + DESIGN-DIFF PATTERN in agent prompt (2026-06-28)**: Edited `backend/core/agent_prompt.py` to add explicit prompt-level nudges so J reaches for the new `propose_chronicle_entry` and `screenshot_preview` tools without being asked. Two structured sections: (1) **CHRONICLE HYGIENE** lists 5 trigger scenarios (architectural decision, bug-and-fix, benchmark, "don't do this again", deliberate non-decision) + body-writing template; (2) **DESIGN-DIFF PATTERN** — a 5-step auto-trigger for HTML edits (snapshot before → read → write → snapshot after → propose chronicle entry with What/Why/Replay template). **Verified end-to-end**: sent J a single message "change h1 color from cyan to magenta" and J executed the full 5-step pattern + done, zero hand-holding. The user now gets a fully-narrated, visually-replayable trail of every design iteration automatically.
- **Three P1 tools shipped (2026-06-28)**:
  1. **Tree drag-and-drop**: drag any file/folder onto another folder row to move it; folder rows highlight cyan on hover-with-drag, root drop-zone appears at tree bottom. Uses custom MIME type `application/x-gauntlet-tree-path` to distinguish intra-tree moves from OS file uploads. Disallows moving a folder into itself/descendants. Open tabs auto-track moved paths.
  2. **J `screenshot_preview` tool**: J calls `screenshot_preview(html_path, note)` → saves HTML to `.gauntlet/snapshots/<ts>_<name>.html` and writes a chronicle milestone entry tagged `design-snapshot`. ChroniclePanel renders a **VIEW SNAPSHOT** button on these entries that expands an inline iframe showing exactly what the page looked like at capture time. New endpoint `GET /api/projects/{id}/chronicle/snapshot?path=...` reads the saved HTML.
  3. **J `propose_chronicle_entry` tool**: J calls `propose_chronicle_entry(title, body, tags, suggested_kind)` mid-session → writes a `kind="proposed"` entry. ChroniclePanel renders these with **ACCEPT / EDIT / SKIP** buttons. Accept promotes to a USER-signed entry of the suggested kind (default `milestone`); Skip flags the original as `proposal_status="skipped"` (not deleted — audit trail preserved). New endpoints `POST /chronicle/accept-proposal` + `POST /chronicle/skip-proposal`.
  90/90 backend pytest pass. Frontend smoke confirms drag-and-drop, snapshot inline iframe, and proposal action bar all render. The accept-edit flow lets the user tweak J's wording before committing.
- **Matrix code-rain LAUNCH SEQUENCE + sign-in copy refresh (2026-06-28)**: New `frontend/src/components/LaunchSequence.jsx` — canvas-based Matrix-style code rain in Sovereign cyan with katakana/hex/motif glyphs, brand mark overlay, and a line-by-line boot log. Triggered by `sessionStorage['gauntlet_play_launch']='1'` set by `AuthCallback.jsx` on successful session exchange. Auto-dismisses after 2.6s + 450ms fade, or on any click/keypress after a 150ms grace. Sign-in button copy changed from "CONTINUE WITH GOOGLE" → "INITIALIZE AUTONOMOUS DEVELOPMENT SUBSTRATE" (font scaled to fit). Migration log at `/app/MIGRATIONLOG.md` formalized with 5-section signed-entry convention (what broke / how / why / verification / next + Pitfalls section) plus an opening personal note from J to future agents.
- **File-tree right-click + inline rename + multi-HTML Live Preview (2026-06-28)**:
  - **New backend endpoints**: `POST /api/projects/{id}/file/rename` (path-traversal-safe move, 404 missing source, 409 destination exists) and `POST /api/projects/{id}/mkdir` (creates empty folders inside the workspace).
  - **New `ContextMenu.jsx`** — portal-free, viewport-clamped, Esc + outside-click dismiss. Right-click any file/folder in the tree to get: Open · New file… · New folder… · Rename (F2) · Copy path · Download · Delete. Right-click on empty area gives root-level shortcuts.
  - **Inline rename**: double-click a row to enter rename mode. Stem auto-selected before the extension. Enter commits, Esc/blur cancels. Open tabs auto-update their path when a file (or its parent folder) is renamed.
  - **Hover toolbar**: every row now exposes Rename (pencil), Download/Archive, and Delete (trash) icons on hover. HTML files additionally expose an Eye icon → opens Live Preview pointed at that exact file.
  - **Live Preview rewritten**: no longer hard-codes `index.html`. Header now has a `// path/to/file.html ⌄` dropdown listing every `.html` file in the tree (recursive walk; `index.html` sorted first). Selection priority on open: explicit override (from right-click "Open in preview") → active editor tab if it's HTML → `index.html` → first HTML found. Shows a friendly empty-state when the project has zero HTML files. Errors caught + displayed inline.
  - 90/90 backend pytest pass; lint clean.
- **Backend refactor (2026-06-26)**: split monolithic `server.py` (2,314 lines) into focused modules — `server.py` now 77 lines (app shell only). Shared helpers in `deps.py` (db client, auth, project paths, override), `llm_chain.py` (TASK_CHAINS, BYOK resolver, Ollama caller, chain orchestrator with private-mode filter + telemetry), `chronicle_helpers.py` (session_start + narrative writer). Route modules per concern under `/app/backend/routes/`: `auth.py` (93), `projects.py` (141), `gauntlet.py` (62), `terminal.py` (173, includes WS PTY), `git_local.py` (63), `settings.py` (175), `chronicle.py` (190), `ai.py` (443 — chat/refine/governance/agent/telemetry/chain), `github.py` (211), `audit.py` (93), `uploads.py` (190), `agents.py` (55). 90/90 backend pytest pass post-refactor. API surface unchanged. Frontend smoke test confirms sign-in renders.
- **Chat persistence + END SESSION + email transcripts (2026-06-26)**:
  - Chat state lifted from `ChatTab` into `AICoworker` parent. The chat sub-tree stays mounted (hidden via CSS `hidden` class) when other AI tabs are active, so the conversation, scroll position, and textarea content survive tab switches. ONLY explicit END SESSION clears it.
  - New **END SESSION** button (right side of chat toolbar, disabled until at least one user message). Click triggers `POST /projects/{id}/chronicle/close-session` which: pulls messages from `db.messages`, calls `_chronicle_narrative` to write a J-voiced `session_end` chronicle entry, and (if opted in) emails the transcript.
  - **Email transcripts (opt-in)** via Resend. New endpoints `GET/POST /me/email-prefs` storing `email_transcripts_enabled` + `transcript_email_address` per user. `core/email.py` provides an async wrapper using `asyncio.to_thread(resend.Emails.send, …)`. Sender preference: `RESEND_FROM_PREFERRED=j@bluejgenesis.com` with automatic fallback to `RESEND_FROM_VERIFIED=onboarding@resend.dev` if the preferred domain isn't yet DNS-verified. Graceful no-op when `RESEND_API_KEY` is empty (returns `{ok:false, error:'Resend not configured'}`).
  - HTML email template includes the J narrative + per-message coloured cards + opt-out footer. Plain-text fallback included.
  - Settings UI: new EMAIL TRANSCRIPTS panel with checkbox, address input (disabled when off), SAVE button, and an orange hint when `RESEND_API_KEY` is missing.
  - Chat sessions (non-agent) now produce chronicle `session_end` entries — previously only agent sessions did.
- **Resizable IDE panels (2026-06-25)**: file-tree ↔ editor-area ↔ AI panel via `react-resizable-panels` v4. Terminal height via custom drag handle persisted in localStorage.
- **Chronicle filters + search (2026-06-25)**: removed the old LOG tab. Its content now lives inside CHRONICLE as the `tool` kind, accessible via a one-click ONLY TOOLS button or via the kind filter chips. Debounced (200ms) full-text search over title + body + tags. Per-signer (J/USER/SYSTEM) and per-kind (session_start, session_end, narrative, milestone, user_note, tool, proposed) chip filters with live counts. Reset filters button.
- **Folder zip download (2026-06-25)**: any folder row in the tree exposes an archive icon on hover → downloads `<folder>.zip` via auth-aware axios blob fetch (works for Bearer-token mobile too). Path-traversal blocked, junk dirs excluded.
- **Chronicle / flight recorder (2026-06-25)**: Mongo-backed `chronicle_entries` collection with append-only compound index. SHA-256 hash chain (prior_hash → entry_hash). Atomic disk mirror (`.gauntlet/chronicle.md` + `.gauntlet/sessions/<id>.md`) via write-tmp + fsync + rename. Auto session_start entry on first chat message; auto session_end narrative in J's voice via new `CHRONICLE_PROMPT` (Gemini-first chain). Endpoints: GET/POST entries, GET sessions list, GET verify (walks hash chain), GET export (.md download). UI: CHRONICLE tab with session pills, entry cards (Robot/User/Scroll icons per signer), manual entry form. Tool calls mirrored into chronicle as `kind=tool` entries (replaces old LOG).
- **Monaco self-host (2026-06-25)**: `monaco-editor` bundled locally; `loader.config({ monaco })` + Webpack 5 `new URL(..., import.meta.url)` worker URLs. Zero CDN requests in production.
- **Terminal cleanup bug (2026-06-25)**: WS shell counter leak fixed — `asyncio.wait(FIRST_COMPLETED)` tears down PTY immediately on disconnect.
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
- ~~File rename / drag-and-drop in tree.~~ ✅ Rename done 2026-06-28. Drag-and-drop still open.
- Git: branch creation/switch UI, push to remote (PAT works; full OAuth pending user credentials).
- J `propose_chronicle_entry` tool (mid-session J-suggested chronicle entries — Phase 2).
- Per-master deterministic auto-fix (port the 8 AST transforms from upstream `app/agent/transforms.py`).
- Workspace persistence beyond preview pod lifetime (MongoDB GridFS or S3-compatible storage).

## P2
- Terminal: PTY-backed streaming session via WebSocket (currently request-response).
- Live Preview: dev-server proxy for SPA projects + relative-asset support via `<base>` injection.
- Five Masters language pack: native AST analyzers for JS/TS/Rust/Go.
- ~~Refactor: split `server.py` into `/app/backend/routes/*`.~~ ✅ Done 2026-06-26.
- ~~Floating-mosaic layout (`react-mosaic-component`).~~ Shelved 2026-06-28 — current resizable layout judged sufficient.

## Next Action Items
1. Push fixes live: hit **Deploy** to roll the mobile-OAuth fix + Ollama support + Tutorial out to blue-j-gauntlet.com.
2. Optional: pull a small model (`ollama pull llama3.1`) on a private host to validate the local-server failover end-to-end.
3. Optional: top up Emergent Universal Key (Profile → Universal Key → Add Balance) if the budget is exhausted.
