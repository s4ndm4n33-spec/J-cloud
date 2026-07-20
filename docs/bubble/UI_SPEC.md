# UI Spec — Pages, Elements, Interactions

Every interactive element gets a **data-testid** (Bubble allows custom attributes on elements). Copy the testid values verbatim so end-to-end QA can drive the app.

Layout: **left sidebar (200px) + main content**. Sidebar contains nav links; main scrolls. Header strip (48px) at top of main with the current page title + a `[SYNC]` refresh button on the right.

---

## Global elements

### Sidebar (fixed)
- Top: J logo (text-only, cyan) — click → `/dashboard`  · testid `sidebar-home`
- Nav items (icons via Phosphor Icons, cyan when active):
  - `Dashboard` · testid `nav-dashboard`
  - `Datasets` · testid `nav-datasets`
  - `Runs` · testid `nav-runs`
  - `Models` · testid `nav-models`
  - `Eval` · testid `nav-eval`
  - `Settings` · testid `nav-settings`
- Bottom: current champion name + eval score badge · testid `sidebar-champion`

### Header strip
- Page title (left, uppercase, tracking-widest)
- Right cluster: `[SYNC]` button (icon-only, spins on click) · testid `header-sync`

### Toast system
Use Bubble's built-in alert element. Position bottom-right. Auto-dismiss 5s.
- Success (cyan border) · testid `toast-success`
- Error (orange border) · testid `toast-error`

---

## `/auth`
Full-screen dark background. Centered card, max-width 480px.

- Logo · testid `auth-logo`
- Backend URL input (default `https://your-devspace.emergentagent.com`) · testid `auth-backend-url`
- Owner token input (masked, type=password) · testid `auth-token-input`
- `[UNLOCK]` button, disabled until both fields filled · testid `auth-unlock-btn`
- Error banner (hidden by default) · testid `auth-error`
- Below card: small text "Owner-only. Non-owner tokens are refused." — muted color

---

## `/dashboard`

### Hero cards (4-column grid, collapses to 2 on mobile)
- Card 1: **VERIFIED ANSWERS** · big number · testid `dash-verified-count`
- Card 2: **TRAINING PAIRS** · big number (SFT + DPO combined) · sub-line breaks down `1284 SFT · 341 DPO` · testid `dash-pairs-count`
- Card 3: **ACTIVE MODEL** · model_id + eval score badge · testid `dash-active-model`
- Card 4: **RUNS IN FLIGHT** · number · click → `/runs?status=running` · testid `dash-inflight`

### Activity feed
- Full-width panel below hero
- Header row: `RECENT ACTIVITY` (uppercase) · `[VIEW ALL]` link
- List: last 10 events, relative timestamp on right · testid `dash-activity-item` (repeats)
- Empty state: `// nothing yet. Export a dataset and start your first run.`

---

## `/datasets`

### Top bar
- Title: `DATASETS`
- Right: `[EXPORT NEW]` button · testid `datasets-new-btn`

### Table
- Repeating group, one row per dataset · testid `datasets-row` (repeats)
- Columns: `id` · `format badge` (SFT cyan / DPO amber) · `filter` · `row_count` (right-aligned) · `size` · `created (relative)` · `status badge` · action buttons
- Row actions:
  - `[PREVIEW]` · testid `dataset-preview-{id}`
  - `[DOWNLOAD]` · testid `dataset-download-{id}` (opens in new tab)
  - `[USE FOR RUN]` · testid `dataset-use-{id}`
- Empty state: `// no datasets yet — click EXPORT NEW to make your first.`

### Export dialog (modal)
- Title: `EXPORT NEW DATASET`
- Format radio: `SFT` / `DPO` · testid `export-format`
- Filter dropdown: all / gauntlet-passed / this-week / this-month · testid `export-filter`
- Row limit input, default 5000 · testid `export-limit`
- Estimated size (auto-calculated: row_count × ~3.5 KB avg) · testid `export-size-estimate`
- Buttons: `[CANCEL]` · `[CREATE]` (disabled while pending) · testid `export-create-btn`

### Preview modal
- Title: `DATASET PREVIEW · {id}`
- Body: monospaced text area, first 20 rows of JSONL syntax-highlighted (Bubble Rich Text is fine)
- `[CLOSE]` · testid `preview-close-btn`

---

## `/runs`

### Top bar
- Title: `RUNS`
- Filter chips: `ALL` · `RUNNING` · `COMPLETE` · `FAILED` · testid `runs-filter-{name}`
- Right: `[NEW RUN]` button · testid `runs-new-btn`

### Table
- Row: `run_id` · status badge (color-coded: queued gray, running cyan pulse, complete viridian, failed orange) · `base_model` · dataset link · `started (relative)` · `duration` · `eval_score` (with Δ badge if promoted) · action cluster
- Row click → `/runs/{run_id}` · testid `runs-row` (repeats)
- Action cluster (compact icons):
  - `View` (arrow icon) · testid `run-view-{id}`
  - `Cancel` (only if running, X icon) · testid `run-cancel-{id}`
  - `Promote` (only if complete + not yet promoted, star icon) · testid `run-promote-{id}`

---

## `/runs/new`

Two-column form (60/40 split on desktop, stacks on mobile).

**Left column** — form:
- Dataset dropdown · testid `newrun-dataset` (searchable, shows format badge in list items)
- Base model dropdown · testid `newrun-base-model`
- Training method radio · testid `newrun-method`
- LoRA rank dropdown · testid `newrun-lora-rank`
- Learning rate slider + numeric input synced · testid `newrun-lr`
- Epochs number input · testid `newrun-epochs`
- Batch size dropdown · testid `newrun-batch-size`
- Notes textarea · testid `newrun-notes`

**Right column** — sticky preview panel:
- Header: `RUN PREVIEW`
- Estimated cost (from formula in API_CONTRACT.md) · testid `newrun-cost`
- Estimated duration: `≈ {epochs × dataset.rows / 1000 × 5} minutes` · testid `newrun-duration`
- Config summary (dl of key values)
- `[LAUNCH]` button, wide · testid `newrun-launch-btn`
- Cancel link back to `/runs` · testid `newrun-cancel`

---

## `/runs/:id` — Run Detail

### Top strip
- Back arrow · testid `rundetail-back`
- Run ID (large, monospaced) · testid `rundetail-id`
- Status badge (large, pulses if running) · testid `rundetail-status`
- Duration counter (updates every second while running) · testid `rundetail-duration`

### Body (3 sections, vertical)

**Section 1 — Metadata card**
- Two-column dl: base_model, method, dataset, lora_rank, learning_rate, epochs, batch_size, cost_usd, modal_task_id
- testid `rundetail-meta`

**Section 2 — Loss chart**
- Line chart (Bubble native or Chart.js plugin) from `loss_history_json`
- Two lines: train_loss (cyan), val_loss (amber)
- X-axis: step, Y-axis: loss
- Auto-updates every 5s during running · testid `rundetail-loss-chart`
- Below chart: min/max/latest labels

**Section 3 — Log tail**
- Text area (monospaced, dark, 400px height) fetching text from `log_tail_url`
- Auto-scrolls to bottom · testid `rundetail-log`
- Copy-log button in corner · testid `rundetail-log-copy`

### Right sidebar (sticky, 240px)
- Status stepper (vertical): queued → running → uploading → evaluating → complete · testid `rundetail-stepper`
- Eval score card (only when complete): score + Δ vs champion · testid `rundetail-eval-card`
- Action buttons stacked:
  - `[PROMOTE]` (green outline, only when complete + not promoted) · testid `rundetail-promote-btn`
  - `[COMPARE]` (secondary) → `/eval?a={id}&b=champion` · testid `rundetail-compare-btn`
  - `[DOWNLOAD ADAPTER]` (only when complete) · testid `rundetail-download-btn`
  - `[CANCEL RUN]` (only when running, red outline) · testid `rundetail-cancel-btn`

---

## `/eval`

### Top bar
- Title: `MODEL COMPARISON`

### Selector strip
- **A** dropdown: any model + `champion` + `base:*` · testid `eval-model-a`
- vs (static)
- **B** dropdown: same options · testid `eval-model-b`
- `[RUN EVAL]` button · testid `eval-run-btn`

### While running
- Progress bar (`{completed} / {total}`) · testid `eval-progress`
- Currently-evaluating item preview (small monospace card) · testid `eval-current-item`

### Results view (when complete)
- Summary card at top:
  - A pass rate + B pass rate + Δ (large number, color-coded)
  - Per-category breakdown as small horizontal bar chart · testid `eval-summary`
- Results table:
  - Columns: prompt_id · category · A verdict badge · B verdict badge · Δ badge
  - Row click → detail modal · testid `eval-row` (repeats)

### Result detail modal
- Full prompt on top
- Two-column diff view: A response vs B response (side-by-side)
- Verdict + score at bottom of each
- testid `eval-detail-modal`

---

## `/models`

### Current champion card (sticky top)
- Large, cyan-bordered
- Model ID, base, eval score, promoted date, `[ROLLBACK]` button · testid `models-champion`

### Table
- Row: `model_id` · base · method · dataset · eval score · promoted_at · champion badge (if is_current_champion) · action cluster
- testid `models-row` (repeats)
- Actions:
  - `[PROMOTE]` (if not champion) · testid `model-promote-{id}`
  - `[DELETE]` (if not champion, > 30d old) · testid `model-delete-{id}`

---

## `/settings`

Simple stacked form.

- Backend URL input · testid `settings-backend-url`
- Owner token input (masked, with reveal button) · testid `settings-token`
- Modal webhook secret input (masked) · testid `settings-modal-secret`
- `[TEST CONNECTION]` button · testid `settings-test-btn`
  - Below: last test result (green "OK · backend v0.9.0" or red error) · testid `settings-test-result`
- `[SAVE]` button · testid `settings-save-btn`
- Divider
- `[SIGN OUT]` button (red outline) · testid `settings-signout-btn`

---

## Loading / empty / error states

Every list view must have three states:
- **Loading** — pulsing skeleton row (Bubble has a preset)
- **Empty** — muted text with call-to-action button
- **Error** — orange border card with error message + `[RETRY]` button

testid pattern for each: `{page}-loading`, `{page}-empty`, `{page}-error`
