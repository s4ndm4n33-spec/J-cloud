# Backend Stubs — What Emergent Must Build

This is the counterpart to `API_CONTRACT.md`. Everything below is a **to-build** list for the Gauntlet DevSpace FastAPI backend. Bubble cannot function until these are live.

**Scope discipline:** every endpoint is owner-only, checked against `OWNER_USER_ID` (already exposed via `deps.OWNER_USER_ID`). Non-owner → 403 `owner_only`. Bubble treats 403 as terminal, 401 as re-auth needed.

## Status as of 2026-07-20

**✅ Stub layer LIVE** — `backend/routes/training.py` registered, all 20 endpoints from `API_CONTRACT.md` return correctly-shaped responses. Bubble can integrate + wire UI immediately. Preview URL:
`https://gauntlet-devspace.preview.emergentagent.com/api/training/health`

What's stubbed:
- All GET endpoints return real Mongo reads against empty collections (returns `[]` and correct sub-shapes)
- `POST /training/datasets`, `/training/runs`, `/training/eval` insert into Mongo and return the row (status set to `queued` / `exporting` — never advances without the workers below)
- `POST /training/runs/{id}/promote`, `/training/models/{id}/promote`, `/training/models/rollback` all work end-to-end against `training_models` collection — the promote flow is fully functional even without training data
- Owner-only guard enforced everywhere: 403 for non-owners

What's NOT stubbed (still to-build):
- `backend/training/exporter.py` — chronicle → SFT/DPO JSONL → S3 upload
- `backend/training/modal_client.py` — Modal SDK dispatch + task tracking
- `backend/training/webhooks.py` — receive Modal progress + completion callbacks (route to be added under `/api/training/webhooks/modal/{run_id}`)
- `backend/training/eval_runner.py` — read `golden.jsonl`, dispatch both models, run Five Masters, write summary
- `llm_chain.resolve_chain()` — dynamic head lookup so a promoted champion actually gets used at runtime (currently `TASK_CHAINS` is static)

## Estimated remaining effort

| Layer | Files touched / created | Effort |
|---|---|---|
| Dataset exporter | `backend/training/exporter.py`, `backend/routes/training.py` | ½ day |
| Modal integration | `backend/training/modal_client.py`, Modal account setup | 1 day |
| Run orchestration | `backend/training/runner.py`, webhook handler | 1 day |
| Model registry + promote | `backend/training/registry.py`, `TASK_CHAINS` integration | ½ day |
| Eval runner | `backend/training/eval_runner.py` | ½ day |
| S3 signed URLs | `backend/core/storage.py` (or use existing) | ¼ day |
| Bubble owner-token auth | reuse existing `get_current_user`, add health endpoint | ¼ day |

**Total: ~4 working days** on the Emergent side, parallelizable with Bubble build.

## Files to create

```
backend/
├── routes/
│   └── training.py                # NEW — 20 endpoints from API_CONTRACT.md
├── training/                      # NEW package
│   ├── __init__.py
│   ├── exporter.py                # chronicle → SFT/DPO JSONL → S3
│   ├── runner.py                  # dispatch Modal task, track status
│   ├── modal_client.py            # Modal SDK wrapper
│   ├── registry.py                # model promote / rollback / champion tracking
│   ├── eval_runner.py             # run golden set against any adapter
│   └── webhooks.py                # receive Modal completion callbacks
├── core/
│   └── storage.py                 # S3/R2 signed URL helper (may exist already)
└── tests/
    └── test_training.py           # NEW — endpoint + logic tests
```

## MongoDB collections (add to existing DB)

```
training_datasets      # exported JSONL metadata
training_runs          # every run
training_models        # promoted adapters (registry)
training_evals         # eval comparisons
training_events        # activity feed
```

Indexes:
- `training_runs.status`, `training_runs.started_at`
- `training_datasets.status`, `training_datasets.created_at`
- `training_models.is_current_champion` (at most one true)
- `training_events.ts` (for feed pagination)

## Env vars (add to `backend/.env`)

Do not commit values. Names only:
- `MODAL_TOKEN_ID` — from `modal token new`
- `MODAL_TOKEN_SECRET`
- `MODAL_APP_NAME` — e.g. `j-training`
- `S3_BUCKET` — e.g. `gauntlet-training-artifacts`
- `S3_REGION`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `TRAINING_ENABLED` — `true` / `false` — master switch
- `TRAINING_MAX_CONCURRENT_RUNS` — safety cap, default 2

`OWNER_USER_ID` already set from prior work. Bubble uses the same owner concept.

## Modal setup (one-time)

```bash
pip install modal
modal token new    # follow the prompt to link your Modal account
modal app deploy backend/training/modal_app.py   # deploy the training image
```

The training image needs: `axolotl`, `transformers`, `peft`, `bitsandbytes`, `accelerate`, and either the base model weights or an on-demand download from HuggingFace.

## Chronicle → SFT JSONL format

Input: `db.chronicle_entries` where `kind='ai_answer'` and `body.verdict='pass'`
Output (one JSON per line):
```json
{"instruction": "Refactor foo() to handle empty list gracefully",
 "input": "def foo(xs):\n    return [x*2 for x in xs]\n",
 "output": "def foo(xs):\n    if not xs:\n        return []\n    return [x*2 for x in xs]\n"}
```

The `instruction` is the user's prompt. `input` is the code context (from `body.prompt` structured field). `output` is J's verified reply, stripped of tool-call blocks.

## Chronicle → DPO JSONL format

Input: `db.knowledge_dpo_candidates` (already stashed by J:MIND rejections) + amendment pairs from chronicle
Output:
```json
{"prompt": "…",
 "chosen": "…verified response…",
 "rejected": "…rejected response…"}
```

## Modal training image (concept)

`backend/training/modal_app.py`:

```python
# CONCEPT ONLY — do not copy verbatim
import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("axolotl", "transformers>=4.44", "peft>=0.13",
                 "bitsandbytes", "accelerate", "trl>=0.11")
    .apt_install("git")
)

app = modal.App("j-training", image=image)

@app.function(gpu="A100-40GB", timeout=7200, secrets=[modal.Secret.from_name("hf-hub")])
def train_sft(dataset_url: str, base_model: str, config: dict) -> dict:
    # 1. Download JSONL from S3
    # 2. Build axolotl config from `config`
    # 3. Run `axolotl.train(cfg)`
    # 4. Save LoRA adapter, upload to S3
    # 5. Return adapter_url, final_loss, duration_seconds
    ...

@app.function(gpu="A100-40GB", timeout=7200, secrets=[modal.Secret.from_name("hf-hub")])
def train_dpo(dataset_url: str, base_model: str, config: dict) -> dict:
    # Same shape but with TRL's DPOTrainer
    ...
```

Modal handles the queue, GPU allocation, and cost billing.

## Webhook flow

1. Bubble → `POST /api/training/runs` on backend
2. Backend inserts `training_runs` row with `status=queued`
3. Backend calls `modal_client.dispatch(run_id, config)` — Modal returns a `task_id`
4. Backend updates row: `status=running`, `modal_task_id=…`, returns 202 to Bubble
5. Modal training script periodically POSTs to `backend/webhooks/modal/{run_id}` with `{step, train_loss, val_loss, log_chunk}` — backend appends to `loss_history` and `log_tail`
6. On completion, Modal POSTs `{status: complete, adapter_url, eval_score_placeholder}` — backend runs eval, then updates row to `status=complete`
7. Bubble's poll loop sees `status=complete`, updates UI

## Promote flow

`POST /api/training/runs/{id}/promote` or `POST /api/training/models/{id}/promote`:

1. Verify not already current champion
2. Mark old champion `is_current_champion = false`, set `demoted_at`
3. Mark new champion `is_current_champion = true`, set `promoted_at`
4. Insert `("owned", "self", model_id)` at the HEAD of `TASK_CHAINS["chat"]` and `TASK_CHAINS["refine"]` and `TASK_CHAINS["agent"]` — meaning: try the fine-tuned model FIRST, fall back to universal/BYOK chain if it fails
5. Reload `llm_chain` module (or use a dynamic chain lookup — see next section)
6. Return new + previous champion IDs (for one-click rollback)

## Making `TASK_CHAINS` dynamic

Currently `TASK_CHAINS` is a static dict in `llm_chain.py`. For runtime promotion, refactor to:

```python
async def resolve_chain(task: str) -> list[tuple]:
    """Get the current chain for a task, including any promoted fine-tuned head."""
    base = TASK_CHAINS_STATIC.get(task, TASK_CHAINS_STATIC["chat"])
    champion = await db.training_models.find_one({"is_current_champion": True})
    if champion and champion.get("enabled_for", []).__contains__(task):
        head = ("owned", "self", champion["model_id"])
        return [head] + base
    return base
```

Then `chain_call` calls `await resolve_chain(task)` instead of reading the static dict.

## Eval endpoint internals

`POST /api/training/eval` reads `backend/tests/eval/golden.jsonl` and for each item:
1. Send prompt to model A → get response A
2. Send prompt to model B → get response B
3. Run Five Masters (`core/fivemasters.evaluate`) on both → get pass/fail/partial verdict
4. Compute delta

Both A and B calls go through the LLM chain infra — same code path as production. For base models (`base:qwen2.5-coder-7b`), call the raw base without any LoRA adapter.

Long-running (60 items × 2 = 120 LLM calls at ~2 sec each = ~4 min). Use the same SSE heartbeat pattern from `_stream_task_with_heartbeats` but for the eval — actually Bubble just polls the `GET /eval/{id}` endpoint, so no SSE needed; just async task + status.

## Testing checklist

Before handing to Bubble:
- [ ] `curl` all 20 endpoints in `API_CONTRACT.md` from a shell — request/response shapes match exactly
- [ ] Export a small SFT dataset (10 rows) — verify JSONL is valid + S3 URL is signed
- [ ] Dispatch a tiny run (1 epoch, LoRA rank 8, 10 examples) — verify Modal fires + webhooks land
- [ ] Promote → verify `TASK_CHAINS` reflects new head → next `/api/ai/chat` uses fine-tuned model
- [ ] Rollback → verify chain restored
- [ ] Non-owner token → verify every training endpoint returns 403
- [ ] Missing token → verify every training endpoint returns 401

## Rollout order

1. **Week 1** — Build endpoints, mock Modal calls with in-memory task simulator. Bubble can develop against this.
2. **Week 2** — Wire up real Modal + S3. Test a real 7B LoRA run end-to-end.
3. **Week 3** — Hand backend URL + token to Bubble. Debug integration.
4. **Week 4** — First real training run promoted to champion. Watch it beat the base model on `golden.jsonl`.

## Cost expectations

- **Modal free tier:** $30/month credit. That's ~15-20 LoRA runs on 7B before you're out.
- **S3 / R2:** ~$0.20/month for typical volumes (adapters are 30-100 MB each).
- **Bubble free:** $0 (subject to their workflow-run limits).

**Total floor to run this for a month: ~$5** if you overshoot Modal's free credit. Under Sanjay's threshold for a "free tier experiment."

## Signed: E1 for Emergent

This spec is the contract. If Bubble reports "the API doesn't return the shape it should" — the mismatch is either in `API_CONTRACT.md` (fix here) or in the backend impl (fix in the training package). Never let a mismatch fester.
