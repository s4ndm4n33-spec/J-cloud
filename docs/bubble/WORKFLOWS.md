# Bubble Workflows

The finite-state machine behind the UI. Every workflow is defined as **trigger → conditions → actions**. Bubble's visual editor takes each block; the intent below is what to wire.

Naming convention: `WF_{page}_{event}`.

---

## Global workflows

### `WF_app_load`
**Trigger:** page load (any page)
**Actions:**
1. If `current user's api_token is empty` → navigate to `/auth`
2. Else make API call `GET /api/training/health` with `Authorization: Bearer {current_user.api_token}`
3. If response is 401 → clear `current user.api_token`, navigate to `/auth`
4. If response is 403 → set `auth-error` = "Owner-only" and navigate to `/auth`
5. If response is 200 + `owner: true` → set `current user.is_owner = yes`, continue

### `WF_header_sync_click`
**Trigger:** `[SYNC]` button click (any page)
**Actions:** re-run the current page's data-loading workflow (see per-page below)

### `WF_api_401_handler` (custom event)
Called by any workflow that catches 401.
**Actions:**
1. Toast error "Session expired"
2. Clear `current user.api_token`
3. Navigate to `/auth`

---

## `/auth` page

### `WF_auth_unlock_click`
**Trigger:** `[UNLOCK]` click
**Conditions:** both inputs non-empty
**Actions:**
1. Set `current user.backend_url` = auth-backend-url input value
2. Set `current user.api_token` = auth-token-input value
3. API call `GET /api/training/health` with Bearer header
4. If 200 + `owner: true`:
   - Set `current user.is_owner = yes`
   - Navigate to `/dashboard`
5. Else:
   - Set `auth-error` visible with response body
   - Clear api_token from user

---

## `/dashboard` page

### `WF_dashboard_load`
**Trigger:** page load OR sync click
**Actions:**
1. API call `GET /api/training/stats` → set state `stats`
2. API call `GET /api/training/activity?limit=10` → set state `events`
3. Populate hero cards from `stats`
4. Populate activity feed from `events`

### `WF_dashboard_recurring_refresh`
**Trigger:** every 30 seconds while on `/dashboard`
**Actions:** call `WF_dashboard_load` (silently, no loading skeletons)

---

## `/datasets` page

### `WF_datasets_load`
**Trigger:** page load OR sync click
**Actions:** API call `GET /api/training/datasets` → populate table

### `WF_datasets_new_click`
**Trigger:** `[EXPORT NEW]` click
**Actions:** open export dialog modal

### `WF_datasets_export_create`
**Trigger:** `[CREATE]` in export dialog
**Actions:**
1. Disable button, show spinner
2. API call `POST /api/training/datasets` with form values
3. On 202: close modal, toast "Exporting dataset…", start `WF_datasets_poll_export(dataset_id)`
4. On error: show error inline

### `WF_datasets_poll_export(dataset_id)` (custom event, recursive)
**Actions:**
1. Wait 3 seconds
2. API call `GET /api/training/datasets/{dataset_id}`
3. If `status = ready` → refresh table, toast "Dataset {id} ready", stop polling
4. If `status = failed` → toast error, stop polling
5. Else → schedule self (call `WF_datasets_poll_export(dataset_id)` again)
Max iterations: 100 (safety cap for free-tier workflow budget)

### `WF_dataset_preview_click(dataset_id)`
**Trigger:** row `[PREVIEW]` click
**Actions:**
1. API call `GET /api/training/datasets/{dataset_id}` (fetches fresh with preview[])
2. Populate preview modal
3. Show preview modal

### `WF_dataset_use_for_run_click(dataset_id)`
**Trigger:** row `[USE FOR RUN]` click
**Actions:**
1. Set page var `preselected_dataset_id = dataset_id`
2. Navigate to `/runs/new`

---

## `/runs` page

### `WF_runs_load`
**Trigger:** page load OR sync click OR filter chip click
**Actions:** API call `GET /api/training/runs?status={active_filter}` → populate table

### `WF_runs_new_click`
**Trigger:** `[NEW RUN]` click
**Actions:** navigate to `/runs/new`

### `WF_run_cancel_click(run_id)`
**Trigger:** row cancel action
**Actions:**
1. Confirm dialog: "Cancel run {run_id}?"
2. If confirmed: API call `POST /api/training/runs/{run_id}/cancel`
3. Refresh table, toast "Run cancelled"

### `WF_run_promote_click(run_id)`
**Trigger:** row promote action
**Actions:**
1. Confirm dialog: "Promote {run_id} to champion?"
2. If confirmed: API call `POST /api/training/runs/{run_id}/promote`
3. Toast "New champion: {run_id}", refresh table, update sidebar champion badge

---

## `/runs/new` page

### `WF_newrun_load`
**Trigger:** page load
**Actions:**
1. API call `GET /api/training/datasets?status=ready` → populate dataset dropdown
2. API call `GET /api/training/base_models` → populate base model dropdown
3. Set default form values
4. If page var `preselected_dataset_id` set → pre-fill dataset dropdown

### `WF_newrun_form_change` (fires on any form input change)
**Actions:** recompute cost estimate + duration estimate from formula in API_CONTRACT.md, update sidebar

### `WF_newrun_launch_click`
**Trigger:** `[LAUNCH]` click
**Actions:**
1. Disable button
2. API call `POST /api/training/runs` with form JSON
3. On 202: navigate to `/runs/{returned_run_id}`
4. On error: show error inline, re-enable button

---

## `/runs/:id` page

### `WF_rundetail_load`
**Trigger:** page load OR sync click
**Actions:**
1. API call `GET /api/training/runs/{page_run_id}` → set state `run`
2. Populate all sections
3. If `run.status in [queued, running, uploading, evaluating]` → start `WF_rundetail_poll`
4. If `run.log_tail_url` non-null → start `WF_rundetail_log_poll`

### `WF_rundetail_poll` (recursive, every 5 s)
**Actions:**
1. Wait 5 seconds
2. API call `GET /api/training/runs/{page_run_id}`
3. Update state `run`, update chart from `loss_history`
4. If `status in [complete, failed, cancelled]` → toast state change, stop polling, refresh sidebar champion badge
5. Else → schedule self

### `WF_rundetail_log_poll` (recursive, every 3 s)
**Actions:**
1. Wait 3 seconds
2. API call `GET {run.log_tail_url}` (raw text response)
3. Append to log tail element, scroll to bottom
4. If run.status not in flight → stop polling

### `WF_rundetail_promote_click`
**Trigger:** `[PROMOTE]` click
**Actions:**
1. Confirm dialog
2. API call `POST /api/training/runs/{page_run_id}/promote`
3. Toast "New champion", update sidebar badge, refresh page

### `WF_rundetail_compare_click`
**Trigger:** `[COMPARE]` click
**Actions:** navigate to `/eval?a={page_run_id}&b=champion`

### `WF_rundetail_download_click`
**Trigger:** `[DOWNLOAD ADAPTER]` click
**Actions:** open `run.adapter_url` in new tab

### `WF_rundetail_cancel_click`
**Trigger:** `[CANCEL RUN]` click
**Actions:**
1. Confirm dialog: "Cancel this run? Cost so far ≈ ${cost}"
2. If confirmed: API call `POST /api/training/runs/{page_run_id}/cancel`
3. Toast, refresh

---

## `/eval` page

### `WF_eval_run_click`
**Trigger:** `[RUN EVAL]` click
**Conditions:** both A and B selected, A ≠ B
**Actions:**
1. Disable button
2. API call `POST /api/training/eval` with `{model_a, model_b}`
3. On 202: store `eval_id`, start `WF_eval_poll`

### `WF_eval_poll` (recursive, every 3 s)
**Actions:**
1. Wait 3 seconds
2. API call `GET /api/training/eval/{eval_id}`
3. Update progress bar + current-item preview
4. If `status = complete` → hide progress, show summary + results table, stop polling
5. If `status = failed` → toast error, stop polling
6. Else → schedule self

### `WF_eval_row_click(item)`
**Trigger:** result table row click
**Actions:** open result detail modal with full A/B diff

---

## `/models` page

### `WF_models_load`
**Trigger:** page load OR sync click
**Actions:** API call `GET /api/training/models` → populate champion card + table

### `WF_model_promote_click(model_id)`
**Trigger:** row promote
**Actions:**
1. Confirm: "Promote {model_id} to champion?"
2. API call `POST /api/training/models/{model_id}/promote`
3. Refresh champion card + table, toast

### `WF_model_rollback_click`
**Trigger:** champion card `[ROLLBACK]`
**Actions:**
1. Confirm: "Rollback to base model? J's chain will use the base until you promote another."
2. API call `POST /api/training/models/rollback` (no body → rolls to base)
3. Refresh champion card + table, toast

### `WF_model_delete_click(model_id)`
**Trigger:** row delete
**Actions:**
1. Confirm: "Delete {model_id}? This cannot be undone."
2. API call `DELETE /api/training/models/{model_id}`
3. On 400 (protected) → toast error with reason
4. On 200 → refresh table, toast

---

## `/settings` page

### `WF_settings_load`
**Actions:** populate inputs from `current user` fields

### `WF_settings_test_click`
**Trigger:** `[TEST CONNECTION]` click
**Actions:**
1. API call `GET /api/training/health` with the INPUT values (not saved yet)
2. Show green/red result box with backend version

### `WF_settings_save_click`
**Trigger:** `[SAVE]` click
**Actions:**
1. Copy input values to `current user` fields
2. Toast "Saved"

### `WF_settings_signout_click`
**Trigger:** `[SIGN OUT]` click
**Actions:**
1. Confirm dialog
2. Clear `current user.api_token`
3. Navigate to `/auth`

---

## Global recurring workflow limits

**Free tier: ~200 workflow runs/day for scheduled actions.** Design constraints:

- Only ONE recurring poll at a time. If user navigates from `/runs/:id` to `/models`, the `WF_rundetail_poll` must stop.
  → Implement by checking `Current page path` inside the recursive workflow and short-circuiting if it changed.
- Dashboard 30-second recurring refresh is optional — comment out if it burns budget.
- `WF_datasets_poll_export`, `WF_rundetail_poll`, and `WF_eval_poll` all have max iteration counters (100 for export, 200 for run/eval) to prevent runaway loops in edge cases.
