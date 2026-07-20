# J Training Console — Bubble.io Product Spec (paste this into Bubble AI)

> This is the primary spec. Paste this document as-is into Bubble AI's project brief field. Attach the other `.md` files in this folder as reference documents. The finished app should be **owner-only**, auth-gated, and connect to an external REST API for all data operations.

---

## Product name
**J Training Console**

## Tagline
*The training layer for Gauntlet DevSpace. Turn every verified answer into weights you own.*

## Purpose

Gauntlet DevSpace is a deterministic AI coding IDE. Every J answer is signed, hash-chained, and graded by an automated verifier (the "Gauntlet"). The result is a growing corpus of high-quality (prompt → response → verdict) triples living in a Mongo backend.

The **J Training Console** is a Bubble app that lets the owner:

1. **Export** that corpus as SFT / DPO training JSONL
2. **Dispatch** fine-tune runs to Modal.com (LoRA on Qwen2.5-Coder-7B / Llama-3.1-8B)
3. **Track** runs live (queued → running → uploading → evaluating → complete)
4. **Evaluate** each new adapter against a golden eval set (~60 held-out items)
5. **Promote** winners to J's LLM chain (or roll back)
6. **Compare** any two models side-by-side on the eval set

The console never runs training code itself. It's the **cockpit** — the API-driven UI, workflow orchestration, and single source of truth for the training history. All heavy lifting happens in the FastAPI backend and Modal.

## User

**Exactly one user**: the app owner. Auth is a single shared bearer token entered on first launch and stored in Bubble's built-in User table. No sign-up flow, no multi-tenant. The token is passed as an `Authorization: Bearer …` header to every API Connector call.

If the token is missing or backend returns 401 → redirect to `/auth`. If backend returns 403 → show "Owner-only" message.

## Design vibe

Match Gauntlet DevSpace's existing aesthetic (see `DESIGN.md` for tokens):
- Dark background (`#0A0E14` void)
- Cyan accents (`#7EE1E5`)
- Monospaced UI type (JetBrains Mono / IBM Plex Mono)
- Left-aligned, information-dense layouts
- No emoji as UI icons (use Phosphor Icons)
- Subtle grid lines instead of drop shadows

Feel: **NASA mission control meets terminal**. Every number matters. Every button does exactly what it says.

---

## Pages / navigation

Single-page app with left sidebar navigation. Six sections:

### 1. `/dashboard`
Landing page after auth. Four hero cards + a live-activity feed:
- **Total verified answers** (from `/api/training/stats` → `verified_count`)
- **Available training pairs** (SFT + DPO, from `/api/training/stats`)
- **Active model** (currently promoted adapter name + eval score)
- **Runs in flight** (from `/api/training/runs?status=running`)
- Below cards: **Recent activity** timeline — last 10 events (run started, run completed, model promoted, dataset exported) with relative timestamps

### 2. `/datasets`
Table of every exported dataset. Columns:
- `id` · `format` (sft / dpo) · `created_at` · `row_count` · `size_mb` · `filter` (all / gauntlet-passed / this-week / this-month) · **actions**

Row actions:
- **Preview** — modal showing first 20 rows of JSONL, syntax-highlighted
- **Download** — signed S3 URL from `/api/training/datasets/{id}/download`
- **Use for run** — jumps to `/runs/new` with dataset pre-selected

Top bar has **[EXPORT NEW]** button → opens dialog with:
- Format dropdown (SFT / DPO)
- Filter dropdown (all / gauntlet-passed / date-range / by-domain)
- Row limit input (default 5000)
- **CREATE** button → `POST /api/training/datasets`

### 3. `/runs`
Table of every training run. Newest first. Columns:
- `run_id` · `status` (queued / running / uploading / evaluating / complete / failed) with color-coded badge · `base_model` · `dataset` (linkable) · `started_at` · `duration` · `eval_score` (with Δ vs base) · **actions**

Row actions:
- **View** → `/runs/:id` detail page
- **Cancel** (if running) → `POST /api/training/runs/{id}/cancel`
- **Promote** (if complete + not yet promoted) → confirm dialog → `POST /api/training/runs/{id}/promote`

Top bar has **[NEW RUN]** button → opens `/runs/new`

### 4. `/runs/new`
Form to dispatch a new training run:
- **Dataset** — searchable dropdown of datasets from `/api/training/datasets`
- **Base model** — dropdown: `qwen2.5-coder-7b`, `qwen2.5-14b-instruct`, `llama-3.1-8b-instruct`, `mistral-7b-v0.3` (or fetch dynamically from `/api/training/base_models`)
- **Training method** — radio: SFT · DPO
- **LoRA rank** — dropdown: 8 · 16 · 32 · 64 (default 16)
- **Learning rate** — slider from 1e-5 to 3e-4 (default 5e-5 SFT, 5e-6 DPO)
- **Epochs** — number input (default 3 SFT, 1 DPO)
- **Batch size** — dropdown: 1 · 2 · 4 · 8 (default 2)
- **Notes** — free-text tag for later grouping
- Cost estimate updates live (approximate — display "≈ $1.20 on Modal A100" based on base_model × epochs × dataset_size)
- **[LAUNCH]** button → `POST /api/training/runs` → redirects to `/runs/:id`

### 5. `/runs/:id` — Run Detail Page
The most-used view during active training. Three sections:

**Top:** run metadata (all fields from `/api/training/runs/:id`), status badge, "duration so far" counter

**Middle:** live loss curve (Chart.js or Bubble's native chart) reading `loss_history[]` — polls every 5 s while `status === "running"`. Two lines: `train_loss` cyan, `val_loss` amber

**Bottom:** live log tail (`log_tail_url` from response, fetched via API Connector as text; scrolls to bottom on update)

Right sidebar (sticky):
- Status timeline (queued → running → uploading → evaluating → complete) as a vertical stepper
- Eval score delta vs current champion (`+3.2%` in cyan, `-1.1%` in amber)
- **[PROMOTE]** button — only shown when `status === "complete"` and `promoted_at === null`
- **[COMPARE]** button → `/eval?a=:id&b=current_champion`
- **[DOWNLOAD ADAPTER]** button → `/api/training/runs/:id/adapter`

### 6. `/eval`
Side-by-side model comparison on the golden eval set (60 items, ~2 minutes to run).

Top bar:
- **Model A** dropdown (any completed run OR current champion OR any base model)
- **Model B** dropdown (same options)
- **[RUN EVAL]** button → `POST /api/training/eval` → shows progress bar → results

Results table (per-item):
- `prompt_id` · `category` · `expected` (truncated) · **A response** · **A verdict** (pass/fail/partial) · **B response** · **B verdict** · **Δ**

Summary card at top:
- A total pass rate · B total pass rate · Δ · per-category breakdown

Row click → modal showing full prompt + both responses + both verdicts + rationale

### 7. `/models`
Model registry — every adapter that has ever completed a run.

Table columns:
- `model_id` · `base_model` · `training_method` · `dataset` · `eval_score` · `promoted_at` (null if never promoted) · `is_current_champion` (bool) · **actions**

Row actions:
- **Promote** (if not champion) → confirm dialog → `POST /api/training/models/{id}/promote`
- **Rollback** (if champion) → confirm dialog → `POST /api/training/models/rollback`
- **Delete** → confirm dialog → `DELETE /api/training/models/{id}` (only allowed if not champion and > 30 days old)

Top bar shows **Current champion** as a highlighted panel.

### 8. `/settings`
Simple settings page:
- Backend API base URL (input, stored in Bubble app data)
- Owner bearer token (masked input, stored in Bubble User)
- Modal.com webhook secret (masked input, forwarded to backend on save)
- **[TEST CONNECTION]** button → `GET /api/training/health` → shows green/red
- **[SIGN OUT]** button → clears token, redirects to `/auth`

### 9. `/auth`
Single-screen bearer token entry:
- Full-screen dark background with centered card
- Bubble field: "Backend URL" (default `https://your-devspace.emergentagent.com`)
- Bubble field: "Owner API token" (masked)
- **[UNLOCK]** button → validates via `GET /api/training/health` with header → on 200 stores token in current User and redirects to `/dashboard` → on 401/403 shows red "Access denied" message

---

## Workflows (business logic)

See `WORKFLOWS.md` for step-by-step Bubble Workflow definitions. The critical ones:

1. **On app load** — check current user has token; if not, redirect to `/auth`
2. **On `/runs/:id` load** — start recurring workflow that polls `/api/training/runs/:id` every 5 s while `status !== "complete"` and `status !== "failed"`
3. **On dataset export success** — refresh `/datasets` table + toast "Dataset ready"
4. **On run promotion success** — refresh `/models`, mark old champion `is_current_champion=false`, mark new one `true`, toast "New champion: model_id"
5. **On API 401** — clear stored token, redirect to `/auth`
6. **On API 5xx** — toast error, keep user on page

---

## API integration

All backend calls go through Bubble's **API Connector** plugin. Every call includes:
- Header: `Authorization: Bearer {current_user.api_token}`
- Header: `Content-Type: application/json` for POSTs
- Base URL: `{current_user.backend_url}` (from Settings)

See `API_CONTRACT.md` for the full list of endpoints with request/response shapes. **20 endpoints total.**

---

## Success criteria (how we know Bubble shipped it right)

1. Owner enters bearer token → lands on Dashboard with real numbers loaded
2. Clicks "Export new dataset" with format=SFT, filter=gauntlet-passed → dataset appears in `/datasets` within 10 s
3. Starts a new run using that dataset + `qwen2.5-coder-7b` + defaults → `/runs/:id` opens and shows the run status transitioning from `queued` to `running` within 30 s
4. Loss curve updates in real time (poll-based, every 5 s)
5. Eventually run completes with an eval score → **[PROMOTE]** button appears
6. Clicks Promote → new champion reflected on Dashboard and `/models`
7. Rolls back → old champion restored
8. Every page has a data-testid on interactive elements (see `UI_SPEC.md`) so we can automate QA against the finished Bubble app

---

## Deliverable format

At end of build, send back:

1. **Live Bubble app URL** (`your-app.bubbleapps.io`)
2. **Screenshots** of every page in both empty state and populated state
3. **API Connector export** (Bubble → Settings → API → Export) as JSON
4. **List of any spec ambiguities** you resolved yourself — so we can fold answers back in

---

## What NOT to build

Explicit non-goals — Bubble does *not* need to implement any of these:

- ❌ The actual training loop (Modal runs this)
- ❌ GPU orchestration (backend `/api/training/runs` handles Modal SDK calls)
- ❌ Dataset storage (backend uploads to S3/R2; Bubble stores only the URL)
- ❌ Real-time WebSocket streaming (use polling every 5 s during active runs)
- ❌ Multi-user auth / sign-up (single owner, single token)
- ❌ Custom domain / SSL (free tier limitation, we accept `bubbleapps.io`)
- ❌ Native mobile apps (responsive web is enough — Bubble handles this)

---

## Timeline expectation

- Bubble AI first-pass scaffold: **~15 min** (auto-generates 60% of UI from this doc)
- Manual API Connector wiring: **~2 hr** (20 endpoints from `API_CONTRACT.md`)
- Workflow wiring per `WORKFLOWS.md`: **~4 hr**
- Design polish per `DESIGN.md`: **~3 hr**
- End-to-end QA against success criteria: **~2 hr**

**Total: 1–2 working days** for a Bubble-native builder.

---

**End of primary spec. See reference docs for deep detail on any section.**
