# Bubble Data Types

Bubble's built-in Postgres-lite database. Create these Data Types with the fields below.

**Key principle:** Bubble stores **metadata**, not payloads. Actual JSONL / adapter files stay on backend S3. Bubble just holds IDs, URLs, status, and display-friendly denormalizations.

---

## `User` (extend built-in)
Existing Bubble User type. Add fields:
- `api_token` — text — the owner's bearer token (masked in UI)
- `backend_url` — text — base URL (`https://…emergentagent.com`)
- `is_owner` — yes/no — set to `yes` after successful `/health` check
- `last_verified_at` — date

---

## `Dataset`
Mirror of backend's dataset export metadata.

| Field | Type | Notes |
|---|---|---|
| `dataset_id` | text | matches backend `id` (e.g. `ds_47`) — **unique index** |
| `format` | text | `sft` or `dpo` |
| `filter` | text | `all` / `gauntlet-passed` / `this-week` / `this-month` / etc. |
| `row_count` | number | |
| `size_mb` | number | |
| `status` | text | `pending` / `exporting` / `ready` / `failed` |
| `download_url` | text | signed S3 URL — refresh on each detail load |
| `preview_json` | text | JSON string of first 20 rows |
| `created_at` | date | |

---

## `TrainingRun`
Mirror of backend's run row.

| Field | Type | Notes |
|---|---|---|
| `run_id` | text | matches backend `run_id` (e.g. `r_9x2f`) — **unique** |
| `status` | text | `queued` · `running` · `uploading` · `evaluating` · `complete` · `failed` · `cancelled` |
| `base_model` | text | |
| `training_method` | text | `sft` / `dpo` |
| `dataset_id` | text | FK to `Dataset.dataset_id` |
| `dataset_row_count` | number | denormalized for table display |
| `lora_rank` | number | |
| `learning_rate` | number | |
| `epochs` | number | |
| `batch_size` | number | |
| `notes` | text | |
| `started_at` | date | |
| `completed_at` | date | nullable |
| `duration_seconds` | number | nullable |
| `eval_score` | number | 0.0 to 1.0, nullable until eval done |
| `delta_vs_champion` | number | nullable |
| `promoted_at` | date | nullable — non-null = this run's adapter is deployed |
| `cost_usd` | number | actual, filled by backend after Modal reports |
| `loss_history_json` | text | JSON string of `[{step, train_loss, val_loss}, …]` — updated by poll |
| `log_tail_url` | text | |
| `adapter_url` | text | signed S3 URL when complete |
| `modal_task_id` | text | for debugging |

---

## `Model`
The registry — every completed run becomes a Model row.

| Field | Type | Notes |
|---|---|---|
| `model_id` | text | e.g. `j-v42-lora` — **unique** |
| `run_id` | text | FK to TrainingRun |
| `base_model` | text | |
| `training_method` | text | |
| `dataset_id` | text | |
| `eval_score` | number | |
| `promoted_at` | date | nullable |
| `is_current_champion` | yes/no | **at most one row can have this true** |
| `created_at` | date | |

---

## `EvalRun`
Comparison runs (`/eval` page).

| Field | Type | Notes |
|---|---|---|
| `eval_id` | text | e.g. `ev_5c1a` — **unique** |
| `status` | text | `queued` / `running` / `complete` / `failed` |
| `model_a` | text | |
| `model_b` | text | |
| `progress_completed` | number | |
| `progress_total` | number | |
| `a_pass_rate` | number | nullable |
| `b_pass_rate` | number | nullable |
| `delta` | number | nullable |
| `by_category_json` | text | JSON string of category breakdown |
| `items_json` | text | JSON string of per-item results (60 rows) |
| `created_at` | date | |

---

## `ActivityEvent`
Dashboard timeline feed. Backend supplies these; Bubble mirrors them.

| Field | Type | Notes |
|---|---|---|
| `event_id` | text | — **unique** |
| `type` | text | `run.completed` / `dataset.exported` / `model.promoted` / etc. |
| `message` | text | pre-formatted display string |
| `run_id` | text | nullable |
| `dataset_id` | text | nullable |
| `model_id` | text | nullable |
| `ts` | date | |

---

## Storage notes

- Bubble free tier: **100 MB total database storage.** Every field above is text/number/date — tiny. Even at 10,000 training runs + eval items, you'd use <10 MB.
- **Do NOT store dataset JSONL or adapter files in Bubble.** Store only the S3 URL.
- Preview JSON is capped at first 20 rows to keep row size sensible.
- Loss history JSON grows during a run — cap at 500 datapoints on backend side. That's plenty for a curve.

---

## Privacy / cascade rules

- Deleting a `Dataset` cascades to related `TrainingRun`s: sets their `dataset_id` to `null` and updates the display to show `— dataset deleted —`. Backend enforces this; Bubble just refreshes.
- Deleting a `TrainingRun` cascades to `Model`s the same way.
- Cannot delete the current champion `Model`. Backend returns 400.
- All rows scoped to `is_owner=true` — Bubble Privacy Rules should be set to "only visible if Current User's `is_owner` is yes." Belt-and-suspenders on top of backend's 403.
