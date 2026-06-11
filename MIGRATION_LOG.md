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
