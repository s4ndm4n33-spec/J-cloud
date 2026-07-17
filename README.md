<div align="center">

```
   ▄████  ▄▄▄       █    ██  ███▄    █ ▄▄▄█████▓ ██▓    ▓█████▄▄▄█████▓
  ██▒ ▀█▒▒████▄     ██  ▓██▒ ██ ▀█   █ ▓  ██▒ ▓▒▓██▒    ▓█   ▀▓  ██▒ ▓▒
 ▒██░▄▄▄░▒██  ▀█▄  ▓██  ▒██░▓██  ▀█ ██▒▒ ▓██░ ▒░▒██░    ▒███  ▒ ▓██░ ▒░
 ░▓█  ██▓░██▄▄▄▄██ ▓▓█  ░██░▓██▒  ▐▌██▒░ ▓██▓ ░ ▒██░    ▒▓█  ▄░ ▓██▓ ░
 ░▒▓███▀▒ ▓█   ▓██▒▒▒█████▓ ▒██░   ▓██░  ▒██▒ ░ ░██████▒░▒████▒ ▒██▒ ░
  ░▒   ▒  ▒▒   ▓▒█░░▒▓▒ ▒ ▒ ░ ▒░   ▒ ▒   ▒ ░░   ░ ▒░▓  ░░░ ▒░ ░ ▒ ░░
   ░   ░   ▒   ▒▒ ░░░▒░ ░ ░ ░ ░░   ░ ▒░    ░    ░ ░ ▒  ░ ░ ░  ░   ░
 ░ ░   ░   ░   ▒    ░░░ ░ ░    ░   ░ ░   ░        ░ ░      ░    ░
       ░       ░  ░   ░              ░              ░  ░   ░  ░
```

# **G A U N T L E T   D E V S P A C E**

### `// DETERMINISTIC · AUTONOMOUS · SUBSTRATE`

**A sovereign-shards cloud IDE with an audit-trail spine, a hard floor against AI hallucination, and an agent named J who'd rather block your write than truncate your file.**

[![License](https://img.shields.io/badge/license-proprietary-cyan?style=flat-square)](#)
[![Stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20React%20%2B%20MongoDB-cyan?style=flat-square)](#)
[![LLM](https://img.shields.io/badge/LLM-Claude%204.5%20%2F%20GPT--5.2%20%2F%20Gemini%203%20%2F%20Ollama-cyan?style=flat-square)](#)
[![Chronicle](https://img.shields.io/badge/audit-hash--chained%20chronicle-cyan?style=flat-square)](#)
[![Status](https://img.shields.io/badge/integrity-verified-00d9ff?style=flat-square)](#)

</div>

---

## What this is

Gauntlet DevSpace is a **single-operator cloud IDE** for shipping production code with an LLM coworker that won't lie to you. It looks like VS Code if VS Code had:

- A **Code Integrity Gateway** that physically rejects any file write containing `# ...rest unchanged...` or unbalanced brackets — before the bytes touch disk.
- A **hash-chained Chronicle** (SHA-256, append-only, atomic disk mirror) that records every tool call, decision, and design diff with courtroom-grade replay.
- A **Five Masters AST evaluator** scoring every file on Beauty, Vitality, Truth, Endurance, and Lineage — deterministically, no LLM judgement.
- An **autonomous agent (J)** with full project context, a 5-step Design-Diff Pattern that auto-snapshots HTML changes, and a sardonic terminal-side manner.
- A **destructive-code interlock** that hard-blocks `rm -rf /`, `mkfs.*`, dd-to-disk, fork bombs, and 14 other patterns at the bash level — bypass only via password-gated single-use override token.
- An **LLM failover chain** (Universal Key → BYO OpenAI/Anthropic/Gemini → local Ollama) that swaps providers in milliseconds when one degrades.
- A **Private Mode toggle** that physically excludes every cloud provider — Ollama-only — so sensitive code never leaves your network.

It is not a toy. It is built on the premise that **if it can't prove integrity, it halts.**

---

## Quick look

```
┌─────────────────┬──────────────────────────────────┬─────────────────────┐
│                 │                                  │                     │
│   FILE TREE     │      MONACO MULTI-TAB EDITOR     │  AI COWORKER (J)    │
│                 │                                  │  ─────────────────  │
│   ▸ src/        │  ```python                       │  CHAT               │
│   ▸ pages/      │  def greet(name: str) -> str:    │  REFINE  (⌘K)       │
│     index.html  │      return f"Hello, {name}"     │  GAUNTLET           │
│     about.html  │  ```                             │  AUDIT (100-pt)     │
│   ▸ .gauntlet/  │                                  │  CHRONICLE          │
│     snapshots/  │  ──────────────────────────────  │  TRACE              │
│     chronicle.md│  $ pytest tests/                 │                     │
│                 │  ...... 90 passed in 41s        │  [INTEGRITY HALT]   │
│                 │                                  │  [PRIVATE MODE]     │
└─────────────────┴──────────────────────────────────┴─────────────────────┘
                  Resizable panes + interactive PTY terminal
```

---

## Operating principles

> These aren't aspirations. They are enforced in code. Look at the file paths.

| # | Principle | Where it lives |
|---|---|---|
| 1 | **No truncation. No hallucination. No silent failures.** | [`backend/core/code_integrity.py`](backend/core/code_integrity.py) |
| 2 | **Every action is signed, hash-chained, and atomically mirrored to disk.** | [`backend/core/chronicle.py`](backend/core/chronicle.py) |
| 3 | **AST-deterministic quality scoring beats LLM-judged code review.** | [`backend/core/fivemasters.py`](backend/core/fivemasters.py) |
| 4 | **Destructive operations halt by default. Override is single-use and password-gated.** | [`backend/core/destructive.py`](backend/core/destructive.py) |
| 5 | **The LLM is interchangeable. The integrity floor is not.** | [`backend/llm_chain.py`](backend/llm_chain.py) |
| 6 | **Sensitive code never has to leave the network.** | Private Mode toggle in TopBar |
| 7 | **The Chronicle is the source of truth. Future agents read it.** | [`/app/MIGRATIONLOG.md`](MIGRATIONLOG.md) |

---

## The J persona

J is your AI coworker. J has tools. J also has rules.

- J runs through a **5-step Design-Diff Pattern** automatically on any meaningful HTML change: before-snapshot → read → write → after-snapshot → chronicle entry.
- J **proposes chronicle entries** mid-session for architectural decisions, bug-and-fix moments, benchmarks, and "don't do this again" lessons. You ACCEPT / EDIT / SKIP — J never assumes.
- J **cannot truncate a file** even if it wanted to — the Integrity Gateway is upstream of every disk write.
- J **runs through a failover chain** of LLM providers without telling you which one answered. You see the answer; the telemetry endpoint shows the provenance.
- J **respects Private Mode**. When you flip the lock, J is forced to Ollama-only and refuses to start when no local server is configured.
- J **speaks like a senior engineer who's had two coffees** — terse, technical, occasionally sardonic. Brand-truth, not brand-fiction.

Calling J is one keystroke away (`⌘K` for inline refine, dedicated panel for agent chat).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                  CLIENT                                      │
│  React + Tailwind + Phosphor Icons + Monaco (locally bundled, zero CDN)      │
│  react-resizable-panels · xterm.js · sandboxed iframes for Live Preview      │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │  HTTPS + WebSocket
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                FASTAPI BACKEND                                │
│                                                                              │
│   server.py (77 lines · app shell)                                           │
│      └── routes/ (12 modules, one per concern)                               │
│           auth · projects · gauntlet · terminal · git_local · settings       │
│           chronicle · ai · github · audit · uploads · agents                 │
│                                                                              │
│   deps.py        ◄── shared: DB / auth / paths / override                    │
│   llm_chain.py   ◄── TASK_CHAINS, BYOK resolver, Ollama, telemetry           │
│                                                                              │
│   core/                                                                      │
│      ├── agent_prompt.py   ◄── J's system prompt + hygiene rules             │
│      ├── tools.py          ◄── agent tools (write_file gated by ↓)           │
│      ├── code_integrity.py ◄── DETERMINISTIC PRE-WRITE VALIDATOR             │
│      ├── chronicle.py      ◄── hash-chained audit log                        │
│      ├── fivemasters.py    ◄── AST-based quality score                       │
│      ├── destructive.py    ◄── pattern bank for the hard-block               │
│      └── pty_session.py    ◄── interactive WebSocket terminal                │
└────────────┬─────────────────────────────────────────────────┬──────────────┘
             │                                                 │
             ▼                                                 ▼
┌─────────────────────────────┐              ┌─────────────────────────────────┐
│         MONGODB             │              │     LLM PROVIDERS               │
│  users · sessions           │              │  Universal Key (Emergent)       │
│  projects · messages        │              │  BYO: OpenAI · Anthropic · Gemini│
│  chronicle_entries (h-chain)│              │  Local: Ollama · llama.cpp      │
│  user_provider_keys (AES)   │              │  Failover chain · Private Mode  │
│  llm_telemetry              │              │                                 │
└─────────────────────────────┘              └─────────────────────────────────┘
```

Workspaces live at `WORKSPACE_ROOT/<user_id>/<project_id>/` with auto-seeded
sample files, a `git init`, a `.gauntletignore`, and a `.gauntlet/` folder for
chronicle mirrors, snapshots, and migration logs.

---

## Tech stack

**Frontend** · React 18 · Tailwind CSS · Shadcn UI · Phosphor Icons · Monaco Editor (locally bundled via `craco` + Webpack 5 `new URL(..., import.meta.url)`) · `react-resizable-panels` v4 · `xterm.js` · `axios` with Bearer-token interceptor

**Backend** · FastAPI · Motor (async MongoDB) · `emergentintegrations` · `httpx` · `dulwich` (pure-Python git fallback) · `resend` (transactional email) · `python-pty` (interactive shells) · `cryptography` (AES-GCM keyvault for BYO keys) · `tavily-python` (live web search) · `fastembed` + ONNX Runtime (semantic embeddings for J:MIND, no torch dep) · `qrcode` / `segno` (branded QR generation)

**LLMs** · Claude Sonnet 4.5 (governance) · GPT-5.2 (refine) · Gemini 3 Flash (chat) · Claude Haiku 4.5 / GPT-5.4 Mini (fallback) · any Ollama / llama.cpp / vLLM OpenAI-compat endpoint (BYO + Private Mode)

**Infra** · Kubernetes (Emergent) · Supervisor (process management) · MongoDB · Hot-reload everywhere

---

## Running locally

```bash
# 1. Backend
cd /app/backend
pip install -r requirements.txt
# Required env: MONGO_URL, DB_NAME, EMERGENT_LLM_KEY, WORKSPACE_ROOT, OVERRIDE_PASSWORD
uvicorn server:app --host 0.0.0.0 --port 8001

# 2. Frontend
cd /app/frontend
yarn install
yarn start  # http://localhost:3000

# 3. Run the tests
cd /app/backend
pytest tests/   # 90/90 should pass
```

In production / preview environments, both processes are managed by supervisor with hot reload enabled. **Never modify the supervisor config** — it sets the host/port/CWD that the kube ingress depends on.

---

## Code Integrity Gateway

The single most important file in this codebase.

```python
# backend/core/code_integrity.py

# Before any write_file or append_file lands on disk:
#   1. Truncation regex bank rejects '...', '# rest', '// rest unchanged', etc.
#   2. Stack-walks () [] {} accounting for strings + comments. Unbalanced → reject.
#   3. .py files run through ast.parse(). SyntaxError → reject.
# Rejection bounces back to J as a tool error. J must regenerate the FULL file.
```

If the gate rejects your write, **regenerate the entire file**. Don't try to be clever — the gate doesn't care about clever.

---

## Chronicle
The hash-chained audit log. Every tool call mirrors here automatically as `kind="tool"`. Above that, two voluntary instruments:

- **`propose_chronicle_entry(title, body, tags, suggested_kind)`** — J suggests a chronicle entry for architectural decisions, bug-and-fix lessons, benchmarks. User ACCEPT / EDIT / SKIP.
- **`screenshot_preview(html_path, note)`** — captures the HTML source AS IS for design-review replay. Inline iframe rendering inside the chronicle.

Verify the chain at any time:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     $API_URL/api/projects/$PROJECT_ID/chronicle/verify
# → {"ok": true, "verified": 42, "broken": []}
```

The disk mirror lives at `<project>/.gauntlet/chronicle.md` and per-session entries at `<project>/.gauntlet/sessions/<session_id>.md`. Both are atomic-write (tmp + fsync + rename).

---

## J:MIND — the global learning substrate

**J learns from every web search and every accepted conversation insight, permanently.** J:MIND is a shared, source-cited, semantically-searchable knowledge base living in the `knowledge_facts` collection. Two learn loops:

- **Auto** — every `web_search` (Tavily) auto-distills durable facts into J:MIND, quality-gated against forum noise (title filter, ≥200 char body, Tavily score ≥0.35). Provenance kept per row (`source_url`, `signer`, `ref_count`).
- **Opt-in** — J's `propose_learning` tool creates a proposal; the user ACCEPTS / REJECTS in the MIND panel (right-rail tab, `data-testid="ai-tab-mind"`).

Retrieval is semantic — `fastembed` with `BAAI/bge-small-en-v1.5` (ONNX, ~90MB, no torch dep) computes cosine similarity in-memory. Top-K facts are auto-injected into every agent turn and every `/ai/chat` message. J gets sharper as J:MIND grows; the per-turn cost stays flat regardless of corpus size.

Global scope is deliberate: J learns once, every user benefits. Curated by construction — every row is deletable from the MIND panel, and every insight has a URL you can audit.

### Domain competence

J:MIND has 16 category buckets: `automotive`, `hvac`, `plumbing`, `electrical`, `appliances`, `engineering`, `electronics`, `software`, `devops`, `web-dev`, `data-science`, `physics`, `math`, `chemistry`, `biology`, `general`. When you ask J about a Nissan Versa door lock, a heat pump stuck in cooling mode, or a wire gauge for a 60A subpanel — she engages with the same rigour as a Python bug. She's not a coding assistant with pretensions; she's a full-stack coworker across the physical and digital worlds.

### Endpoints

```
GET  /api/knowledge/stats
GET  /api/knowledge/facts?category=&tag=&q=&limit=
DELETE /api/knowledge/facts/{id}
GET  /api/knowledge/proposals?status=pending
POST /api/knowledge/proposals/{id}/{accept|reject}
POST /api/knowledge/search       # Tavily passthrough + auto-learn
POST /api/knowledge/recall       # semantic recall for UI debug
GET  /api/knowledge/export?format=openai_sft   # streams JSONL for fine-tune
```

---

## Portable J — the framework travels

J's identity, standards, and gauntlet are captured in `/AGENTS.md` at the repo root — the emerging cross-IDE convention adopted by Codex CLI, Aider, Cline, and Sourcegraph Amp. One `bash scripts/sync-j.sh` fans it out to every major AI IDE:

| Destination | Consumed by |
|---|---|
| `AGENTS.md` (root) | Codex, Aider, Cline, Sourcegraph Amp |
| `.cursor/rules/j.mdc` | Cursor (with `alwaysApply: true`) |
| `.github/copilot-instructions.md` | GitHub Copilot in VS Code / JetBrains |
| `CLAUDE.md` | Claude Code |
| `.windsurfrules` | Windsurf |
| `.continue/rules.md` | Continue |
| `.zed/agent.md` | Zed AI |

Any LLM that reads one of these files becomes J for the session — same persona, same Five Masters gauntlet, same CIG rejection rules, same substrate-ownership boundary. Runtime CIG enforcement only happens inside Gauntlet DevSpace (this pod). Outside, the rules are honoured *as instructions*, not walls — a portable pre-commit CIG is planned.

---

## Training pipeline — J is fine-tunable

Because J is a substrate, and the substrate persists on top of any base model, we can distill J-through-CIG behaviour into a smaller open-weight model:

1. **`GET /api/knowledge/export?format=openai_sft`** — streams J:MIND as OpenAI-fine-tune-shaped JSONL, with AGENTS.md as the system prompt on every row.
2. **`GET /api/training/dpo`** — streams DPO-shaped rows from `chronicle_entries` where `kind='ai_answer'`. Every `/ai/chat` and `/ai/agent` call auto-logs an ai_answer row from Feb 2026 forward.
3. **`/backend/tests/eval/golden.jsonl`** — 45 hand-crafted eval prompts across 6 domains (code, mechanical, persona, refusal, tool_use, edge) with rubric-graded ideals.
4. **`scripts/eval_run.py`** — pointable at any OpenAI-compatible endpoint OR Gauntlet's `/api/ai/chat`. Produces per-model CSVs.
5. **`scripts/eval_score.py`** — LLM-judge scorer (free-tier compatible). Prints per-model + per-domain summaries.

Full runbook: `scripts/EVAL_HARNESS.md`. Meta-prompt for authoring more eval prompts on J's own terms: `docs/eval/J_SELF_PORTRAIT.md`.

---



## Five Masters

Every file in your workspace gets a deterministic 5-point score from a pure-AST evaluator:

| Master | What it asks |
|---|---|
| **Beauty** | Is this readable? PEP 8 / Prettier-clean? Reasonable nesting? |
| **Vitality** | Does it run? Does it have tests? Does it actually do the thing? |
| **Truth** | Does the doc match the code? Are the types honest? |
| **Endurance** | Does it handle errors? Is it idempotent where it should be? |
| **Lineage** | Does it cite the standards/PEPs/RFCs it implements? |

Open any file → check the score badge on its tab. Hit the GAUNTLET right-panel tab for a full report with concrete fix suggestions.

---

## Destructive interlock

Patterns blocked at HTTP `/terminal/exec` AND at the bash level (via `extdebug` DEBUG trap inside the interactive PTY):

```
rm -rf /  ·  rm -rf ~  ·  rm -rf /*  ·  rm -rf .  ·  rm -rf ..
mkfs.*
dd of=/dev/{sd,nvme,hd,mmc}*
:(){:|:&};:
chmod -R 777 /
```

To run any of these intentionally:

1. Open the password override modal.
2. Confirm intent.
3. The backend mints a **single-use, 2-minute-TTL override token**.
4. Re-issue the command with the token.

The token consumes on use. No reuse. No bypass. No exceptions.

---

## Private Mode

The lock icon in the TopBar. When engaged:

- The LLM failover chain filters out every non-Ollama step at the orchestrator level.
- The Resolved Chain panel shows every cloud provider as `runnable: false`.
- The backend refuses to enable Private Mode if no local server is configured (clear error message, not a silent failure).

This is the right tool for client work under NDA, ML model weights, financial code, healthcare protocols, or anything else that legally cannot egress.

---

## Files of reference (for new contributors)

| Concern | Read this first |
|---|---|
| Routing | [`backend/server.py`](backend/server.py) → [`backend/routes/`](backend/routes/) |
| LLM orchestration | [`backend/llm_chain.py`](backend/llm_chain.py) |
| Agent tools | [`backend/core/tools.py`](backend/core/tools.py) |
| J's system prompt | [`backend/core/persona.py`](backend/core/persona.py) · [`backend/core/agent_prompt.py`](backend/core/agent_prompt.py) |
| **J:MIND (learning substrate)** | [`backend/core/knowledge.py`](backend/core/knowledge.py) · [`backend/routes/knowledge.py`](backend/routes/knowledge.py) · [`frontend/src/components/KnowledgePanel.jsx`](frontend/src/components/KnowledgePanel.jsx) |
| **Portable J** | [`/AGENTS.md`](AGENTS.md) · [`scripts/sync-j.sh`](scripts/sync-j.sh) · [`docs/workflow/J_PORTABLE.md`](docs/workflow/J_PORTABLE.md) |
| **Training pipeline** | [`scripts/eval_run.py`](scripts/eval_run.py) · [`scripts/eval_score.py`](scripts/eval_score.py) · [`scripts/EVAL_HARNESS.md`](scripts/EVAL_HARNESS.md) · [`backend/tests/eval/golden.jsonl`](backend/tests/eval/golden.jsonl) |
| File tree UX | [`frontend/src/components/FileTree.jsx`](frontend/src/components/FileTree.jsx) |
| IDE shell | [`frontend/src/pages/IDE.jsx`](frontend/src/pages/IDE.jsx) |
| Chronicle UI | [`frontend/src/components/ChroniclePanel.jsx`](frontend/src/components/ChroniclePanel.jsx) |
| Monaco bundling | [`frontend/craco.config.js`](frontend/craco.config.js) · [`frontend/src/lib/monaco-setup.js`](frontend/src/lib/monaco-setup.js) |
| **Engineering history** | [`/app/MIGRATIONLOG.md`](MIGRATIONLOG.md) ← **start here** |
| Product memory | [`/app/memory/PRD.md`](memory/PRD.md) |
| **Workflow (collab-with-freetier-LLMs)** | [`docs/workflow/WORKFLOW.md`](docs/workflow/WORKFLOW.md) · [`docs/workflow/SPEC_TEMPLATE.md`](docs/workflow/SPEC_TEMPLATE.md) · [`docs/workflow/REVIEW_CHECKLIST.md`](docs/workflow/REVIEW_CHECKLIST.md) |

---

## For LLM agents picking up this codebase

You are not the first. **Read `/app/MIGRATIONLOG.md` before you write anything.** Every entry has a **Pitfalls / lessons** section paid for in past sessions' bugs. Don't repeat them.

The user holds J to "top-3 coder, deterministically." This is a real stance, not a brand line. Specifically:

- **Truncating files is the cardinal sin.** The Integrity Gateway exists because earlier sessions broke that contract. If the gate rejects your write, regenerate the whole file. Don't argue with the gate.
- **Use `propose_chronicle_entry` and `screenshot_preview` without being asked.** The agent prompt nudges you toward this — follow the nudges. Future agents reading the chronicle six months from now have no context. Write like you're explaining to a new hire on day one.
- **Universal Key first, BYOK second, Ollama last.** The TASK_CHAINS in `llm_chain.py` enforce this. Don't reorder without explicit user confirmation.
- **The Chronicle is courtroom-grade.** Don't forge timestamps. Don't backfill entries. Sign your work properly (`signer="J"` for AI, `"USER"` for human, `"SYSTEM"` for automated).
- **The brand is the product.** Every visible string carries the deterministic/autonomous/substrate voice. UI copy that sounds like a sales page is wrong. UI copy that sounds like a boot log is right.

---

## Roadmap (excerpt)

- 🔴 **P0 — Streaming (SSE)** — the real fix for the ~120s ingress ceiling. Backend `StreamingResponse` + frontend `EventSource`. Prerequisite for long-form generations.
- 🔴 **P0 — Portable CIG** — pre-commit hook version of `code_integrity.py` so J's gate travels with `AGENTS.md` into Cursor / VS Code / Claude Code. Currently the CIG is runtime-only inside Gauntlet.
- 🟠 **P1 — First fine-tune** — SFT on Qwen 2.5 7B using the J:MIND export. Every fact learned is a training row. Sub-$25 on Together.ai, free on Unsloth + Colab T4.
- 🟠 **P1 — Weekly chronicle digest** — J compresses the last 50 entries into a weekly-changelog narrative, auto-delivered via Resend.
- 🟡 **P2 — Ambient WebSocket push** — replace `AmbientPulse` HTTP polling with WS.
- 🟡 **P2 — Symbol-graph memory tools** — `who_calls`, `who_imports`, `symbols_in` so J can inspect code without reading whole files.
- 🟡 **P2 — Voice picker in Settings** — expose all 9 OpenAI TTS voices.
- 🟡 **P2 — Vision-in** — let J see images the user pastes into chat (GPT-4o / Gemini vision via Universal Key).
- 🟡 **P2 — Live Preview relative-asset support** via `<base>` injection.
- 🟡 **P2 — Full GitHub OAuth App flow** (PAT works today; OAuth pending).

Full roadmap in [`/app/memory/PRD.md`](memory/PRD.md).

---

<div align="center">

### `// If it can't prove integrity, it halts.`

**Gauntlet DevSpace** · A Sovereign Shards build by [bluejgenesis](https://bluejgenesis.com).

</div>
