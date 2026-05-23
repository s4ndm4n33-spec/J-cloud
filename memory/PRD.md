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
- 15/15 backend pytest tests pass (`/app/backend/tests/test_gauntlet_devspace.py`).
- Frontend smoke: sign-in landing renders, IDE shell loads, file open works, single-tab dedupe verified, Gauntlet HUD updates.
- AI endpoints: budget-exhausted path verified to return graceful offline string (no 500).

## Test credentials
See `/app/memory/test_credentials.md`.

## Backlog / P1
- Settings panel for users to provide their own LLM keys (avoid Universal Key budget exhaustion).
- Multi-cursor inline-diff editor for InlineEditModal output (currently full-block replace).
- File rename / drag-and-drop in tree.
- Git: branch creation/switch UI, push to remote (currently local only).
- Per-master deterministic auto-fix (port the 8 AST transforms from upstream `app/agent/transforms.py`).
- Workspace persistence beyond preview pod lifetime (move workspaces to MongoDB GridFS or S3-compatible storage).

## P2
- Terminal: PTY-backed streaming session via WebSocket (currently request-response).
- Live Preview: dev-server proxy for SPA projects (currently raw `index.html` only).
- Five Masters language pack: native AST analyzers for JS/TS/Rust/Go (currently heuristic).
- Telemetry HUD: real uptime, AST pass-rate, refine count micro-numerics in corners.

## Next Action Items
1. Top-up Emergent Universal Key (Profile → Universal Key → Add Balance) — current budget exhausted so chat/refine/governance return graceful offline messages until topped up.
2. Optional: implement the BYO-key settings panel so users can plug in their own provider keys.
3. Optional: integrate the upstream 8 deterministic AST transforms (`/optimize` flow) for one-click Gauntlet fix.
