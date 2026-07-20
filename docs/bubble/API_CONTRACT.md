# API Contract — Bubble ↔ Backend

Every endpoint below is called by Bubble via the **API Connector** plugin. All requests carry:

```
Authorization: Bearer {owner_token}
Content-Type: application/json    (POST/PUT/DELETE only)
```

Backend base URL is stored in Bubble as `current_user.backend_url` (e.g. `https://gauntlet-devspace.preview.emergentagent.com`). Every path is prefixed with `/api`.

**All responses:**
- `200` — success
- `401` — bad/missing token → clear token, redirect to `/auth`
- `403` — non-owner token → show "Owner-only" message
- `404` — resource not found
- `5xx` — server error → toast + retry option

---

## `GET /api/training/health`
Ping. Used by `/auth` and `/settings`.

**Response:**
```json
{
  "ok": true,
  "owner": true,
  "backend_version": "0.9.0",
  "modal_configured": true,
  "storage_configured": true
}
```

If `owner: false` → the token is valid but not the app owner → show "Owner-only" and stay on `/auth`.

---

## `GET /api/training/stats`
Dashboard hero cards.

**Response:**
```json
{
  "verified_answers": 1284,
  "sft_pairs_available": 1284,
  "dpo_pairs_available": 341,
  "active_model": {
    "model_id": "j-v42-lora",
    "base_model": "qwen2.5-coder-7b",
    "eval_score": 0.847,
    "promoted_at": "2026-07-19T21:00:00Z"
  },
  "runs_in_flight": 1,
  "last_updated": "2026-07-20T09:32:11Z"
}
```

---

## `GET /api/training/activity?limit=10`
Timeline feed for dashboard.

**Response:**
```json
{
  "events": [
    {
      "id": "evt_a1b2",
      "type": "run.completed",
      "message": "Run r_9x2f finished — eval score 0.847 (+0.021 vs champion)",
      "run_id": "r_9x2f",
      "ts": "2026-07-20T09:12:03Z"
    },
    {
      "id": "evt_a1b1",
      "type": "dataset.exported",
      "message": "Dataset ds_47 (SFT, 1200 rows) ready",
      "dataset_id": "ds_47",
      "ts": "2026-07-20T08:44:00Z"
    }
  ]
}
```

Event types: `run.started` · `run.progress` · `run.completed` · `run.failed` · `model.promoted` · `model.rolled_back` · `dataset.exported` · `eval.completed`

---

## Datasets

### `GET /api/training/datasets?limit=50`

**Response:**
```json
{
  "datasets": [
    {
      "id": "ds_47",
      "format": "sft",
      "filter": "gauntlet-passed",
      "row_count": 1200,
      "size_mb": 4.2,
      "created_at": "2026-07-20T08:44:00Z",
      "status": "ready",
      "download_url": null
    }
  ],
  "total": 8
}
```

`status`: `pending` · `exporting` · `ready` · `failed`

### `POST /api/training/datasets`

**Request:**
```json
{
  "format": "sft",
  "filter": "gauntlet-passed",
  "row_limit": 5000,
  "date_from": null,
  "date_to": null,
  "domains": []
}
```

**Response:** 202 with dataset row (status = `exporting`). Bubble polls `GET /api/training/datasets/{id}` until `status = ready`.

### `GET /api/training/datasets/{id}`

Same as list-item shape, plus:
```json
{
  "id": "ds_47",
  "format": "sft",
  "row_count": 1200,
  "size_mb": 4.2,
  "status": "ready",
  "download_url": "https://s3.example.com/…?X-Amz-Signature=…",
  "preview": [
    {"instruction": "…", "input": "…", "output": "…"}
  ]
}
```

`preview` is the first 20 rows for the preview modal. `download_url` is a signed S3 URL, valid for 1 hour.

### `DELETE /api/training/datasets/{id}`

Response: `{ "ok": true }`. Fails 400 if referenced by any run.

---

## Runs

### `GET /api/training/runs?limit=50&status=`

**Response:**
```json
{
  "runs": [
    {
      "run_id": "r_9x2f",
      "status": "complete",
      "base_model": "qwen2.5-coder-7b",
      "training_method": "sft",
      "dataset_id": "ds_47",
      "dataset_row_count": 1200,
      "started_at": "2026-07-20T08:50:00Z",
      "completed_at": "2026-07-20T09:12:03Z",
      "duration_seconds": 1323,
      "eval_score": 0.847,
      "delta_vs_champion": 0.021,
      "promoted_at": null,
      "cost_usd": 1.24,
      "notes": "first real run"
    }
  ],
  "total": 12
}
```

`status`: `queued` · `running` · `uploading` · `evaluating` · `complete` · `failed` · `cancelled`

### `POST /api/training/runs`

**Request:**
```json
{
  "dataset_id": "ds_47",
  "base_model": "qwen2.5-coder-7b",
  "training_method": "sft",
  "lora_rank": 16,
  "learning_rate": 5e-5,
  "epochs": 3,
  "batch_size": 2,
  "notes": "first real run"
}
```

**Response:** 202 with full run row, `status = queued`.

### `GET /api/training/runs/{id}`

Full run detail, adds these fields to the list-shape:
```json
{
  "loss_history": [
    {"step": 10, "train_loss": 1.83, "val_loss": 1.79},
    {"step": 20, "train_loss": 1.61, "val_loss": 1.68}
  ],
  "log_tail_url": "https://s3.example.com/logs/r_9x2f.log?…",
  "adapter_url": "https://s3.example.com/adapters/r_9x2f.safetensors?…",
  "config": {
    "modal_task_id": "ta-abc123",
    "gpu": "A100-40GB",
    "framework": "axolotl",
    "training_args": { "…": "…" }
  }
}
```

Loss history is appended by the Modal training job posting back webhooks (see BACKEND_STUBS.md).

### `POST /api/training/runs/{id}/cancel`

Response: `{"ok": true, "run_id": "r_9x2f", "status": "cancelled"}`. Idempotent.

### `POST /api/training/runs/{id}/promote`

Promotes the run's resulting adapter to current champion. Response includes the previous champion for rollback:

```json
{
  "ok": true,
  "new_champion": "r_9x2f",
  "previous_champion": "r_7a12",
  "task_chain_updated": true
}
```

### `GET /api/training/runs/{id}/adapter`

Redirects (302) to signed S3 URL of the `.safetensors` file. Bubble triggers this in a new tab for download.

---

## Models

### `GET /api/training/models?limit=100`

**Response:**
```json
{
  "models": [
    {
      "model_id": "j-v42-lora",
      "run_id": "r_9x2f",
      "base_model": "qwen2.5-coder-7b",
      "training_method": "sft",
      "dataset_id": "ds_47",
      "eval_score": 0.847,
      "promoted_at": "2026-07-19T21:00:00Z",
      "is_current_champion": true,
      "created_at": "2026-07-19T20:45:00Z"
    }
  ],
  "current_champion_id": "j-v42-lora"
}
```

### `POST /api/training/models/{model_id}/promote`
Same response shape as `runs/{id}/promote`.

### `POST /api/training/models/rollback`

**Request:**
```json
{ "to_model_id": "j-v41-lora" }
```

If `to_model_id` omitted → rolls back to the base_model (universal chain step). Response same shape.

### `DELETE /api/training/models/{model_id}`

Fails 400 if the model is the current champion or was promoted within the last 30 days.

---

## Evaluation

### `POST /api/training/eval`

Run any two models against the golden eval set (~60 items).

**Request:**
```json
{
  "model_a": "j-v42-lora",
  "model_b": "j-v41-lora"
}
```

`model_a` / `model_b` accept: `model_id` string · `"champion"` · `"base:qwen2.5-coder-7b"` (any base).

**Response:** 202 with `eval_id`. Bubble polls `GET /api/training/eval/{eval_id}`.

### `GET /api/training/eval/{eval_id}`

**Response:**
```json
{
  "eval_id": "ev_5c1a",
  "status": "complete",
  "model_a": "j-v42-lora",
  "model_b": "j-v41-lora",
  "progress": { "completed": 60, "total": 60 },
  "summary": {
    "a_pass_rate": 0.847,
    "b_pass_rate": 0.826,
    "delta": 0.021,
    "by_category": [
      {"category": "python-refactor", "a": 0.90, "b": 0.85, "n": 20},
      {"category": "js-debug",         "a": 0.75, "b": 0.80, "n": 20},
      {"category": "sql-audit",        "a": 0.90, "b": 0.85, "n": 20}
    ]
  },
  "items": [
    {
      "prompt_id": "g_001",
      "category": "python-refactor",
      "expected": "handle empty list gracefully",
      "a_response": "def foo(xs):\n    if not xs: return []\n    …",
      "a_verdict": "pass",
      "a_score": 1.0,
      "b_response": "def foo(xs):\n    return [x*2 for x in xs]",
      "b_verdict": "fail",
      "b_score": 0.0,
      "delta": 1.0
    }
  ]
}
```

`status`: `queued` · `running` · `complete` · `failed`

### `GET /api/training/base_models`

**Response:**
```json
{
  "base_models": [
    {"id": "qwen2.5-coder-7b", "label": "Qwen 2.5 Coder 7B", "context": 32768, "recommended_for": "code"},
    {"id": "qwen2.5-14b-instruct", "label": "Qwen 2.5 14B Instruct", "context": 32768, "recommended_for": "general"},
    {"id": "llama-3.1-8b-instruct", "label": "Llama 3.1 8B Instruct", "context": 131072, "recommended_for": "long-context"},
    {"id": "mistral-7b-v0.3", "label": "Mistral 7B v0.3", "context": 32768, "recommended_for": "speed"}
  ]
}
```

---

## Cost estimator (client-side hint)

Bubble computes cost estimate for the New Run form using this formula (no API call needed, just JS/logic in the workflow):

```
cost_usd ≈ (dataset.row_count * training_method_factor[method] * epochs * base_model_factor[model] * 1.5e-4)
where training_method_factor = { sft: 1.0, dpo: 2.0 }
      base_model_factor      = { 7b: 1.0, 8b: 1.15, 14b: 2.2 }
```

Display as `≈ $X.XX on Modal A100`. Not authoritative — actual cost is billed by Modal.

---

## Total endpoint count

**20 endpoints.** All owner-only. All return JSON. All support standard `Authorization: Bearer` header.
