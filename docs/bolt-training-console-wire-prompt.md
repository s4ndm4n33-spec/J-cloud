# Bolt Prompt — Wire Training Console to Prod Backend

Paste this whole message into your existing bolt.new Training Console
project as a single follow-up prompt.

---

Wire this app to the production FastAPI backend. Do NOT rebuild the UI —
only replace mock data and stub calls with real HTTP requests. Keep
existing components; just point them at the real API.

## Backend

- Base URL: `https://blue-j-gauntlet.com`
- All endpoints prefixed with `/api`
- Auth: Bearer token in `Authorization` header on EVERY request. Store
  the token in `localStorage.trainingConsoleToken` and read it via a
  single `useOwnerToken()` hook. If the token is missing or a 401 comes
  back, show a "Paste owner token" modal that writes to localStorage.

## Env / config

Add a `Settings` panel (top-right gear) with:
- `apiBaseUrl` (default `https://blue-j-gauntlet.com`)
- `ownerToken` (masked input, stored in localStorage)
- **Test connection** button → `GET /api/training/health`. On 200 render a
  green pill per component:
  - version → shows `v{data.version}` (e.g. `v0.9.1`)
  - storage → green if `data.storage === true`, red otherwise (label: R2)
  - modal → green if `data.modal === true`
  - webhook → green if `data.webhook === true`
  - training_enabled → amber "flag off" if `data.training_enabled === false`
- Show `data.public_backend_url` verbatim under the pills so the user can
  eyeball that prod is targeting itself correctly

Replace the current "OK · backend vundefined" indicator with the version
pill from the response — read `data.version`, NOT `data.backend_version`.

## Endpoint contract

Every response is JSON. All POST bodies are JSON. All endpoints require
the Bearer token.

### Health & stats
```
GET  /api/training/health
    → { ok, owner, version, storage, modal, webhook, public_backend_url,
        training_enabled, backend_version, modal_configured, storage_configured }

GET  /api/training/base_models
    → { models: [{ key, hf_id, size_hint, gated }...] }

GET  /api/training/stats
    → { datasets: n, runs_active: n, runs_complete: n, models: n,
        adapters_total_bytes: n, latest_run: {...} | null }

GET  /api/training/activity
    → { events: [{ ts, kind, ticket_id?, run_id?, note }...] }
```

### Datasets
```
GET    /api/training/datasets                       → { datasets: [...] }
POST   /api/training/datasets                        body: { name, scope, since?, filter? }
                                                     → { dataset_id, size, rows }
GET    /api/training/datasets/{id}                   → { dataset }
GET    /api/training/datasets/{id}/download          → streams JSONL
DELETE /api/training/datasets/{id}                   → { ok }
```

### Runs
```
GET    /api/training/runs                            → { runs: [...] }
POST   /api/training/runs                            body: { dataset_id, base_model,
                                                             training_method, epochs?,
                                                             learning_rate?, lora_r? }
                                                     → { run_id, modal_task_id, status }
GET    /api/training/runs/{run_id}                   → { run: { status, loss_history, ... } }
POST   /api/training/runs/{run_id}/cancel            → { ok }
POST   /api/training/runs/{run_id}/promote           body: { model_name? }
                                                     → { model_id, adapter_url }
GET    /api/training/runs/{run_id}/adapter          → { adapter_url, size_bytes }
```

### Models (trained adapters)
```
GET    /api/training/models                          → { models: [...] }
POST   /api/training/models/{model_id}/promote       → { ok }   # set as active
POST   /api/training/models/rollback                 → { ok }   # revert to base
DELETE /api/training/models/{model_id}               → { ok }
```

### DPO review (rejected Tavily candidates)
```
GET    /api/training/dpo/review                      → { candidates: [...] }
POST   /api/training/dpo/{id}/approve                → { ok }
POST   /api/training/dpo/{id}/reject                 → { ok }
```

### Eval
```
POST   /api/training/eval                            body: { model_id, dataset_id? }
                                                     → { eval_id, status }
GET    /api/training/eval/{eval_id}                  → { eval: { metrics, ... } }
```

## Error handling

- 401 anywhere → force-open the Settings/token modal
- 403 → red banner "owner-only endpoint — this token isn't the owner's"
- 400/500 → toast with the response's `detail` field (already human-readable)
- Network error → offline pill in header

## Polling

- Health pills refresh every 60s
- Runs list refreshes every 15s while any run has status `pending` or
  `running`. Freeze polling when all runs are terminal.
- Run detail refreshes every 5s while running (progress bar animates)

## What NOT to change

- Don't touch the visual design system
- Don't add auth flows other than the Bearer paste
- Don't add pagination (backend caps lists)
- Don't proxy the API — call directly (CORS is permissive)

## First-pass acceptance

1. I paste my Bearer, hit Test Connection, all four green pills light up
2. The Datasets page lists real datasets from prod
3. Creating a run POSTs to `/api/training/runs` and returns a real run_id
4. The Runs page shows my new run, polls it, and eventually renders
   loss_history from the response

Ship v1 wired to prod. Don't mock anything.

---
