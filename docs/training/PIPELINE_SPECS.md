# Training Pipeline — File Specs for J

> Handoff to J for implementation. Every file below has: purpose, exact path,
> imports, function signatures, storage/env contract, and testing strategy.
> Write files in the order listed — each depends on the previous.

---

## Prereqs (before touching code)

### Env vars to add to `/app/backend/.env`
```
# Modal
MODAL_TOKEN_ID=          # from `modal token new`
MODAL_TOKEN_SECRET=
MODAL_APP_NAME=j-training

# Object storage (Cloudflare R2 recommended; S3-compatible API)
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=j-training-artifacts
R2_ENDPOINT=             # https://<account>.r2.cloudflarestorage.com
R2_PUBLIC_URL=           # https://pub-<hash>.r2.dev  (used for adapter downloads)

# Pipeline switches
TRAINING_ENABLED=true
TRAINING_WEBHOOK_SECRET= # random 32-byte hex, shared with Modal container
TRAINING_MAX_CONCURRENT_RUNS=2
```

### Python deps to add via `pip install X && pip freeze > /app/backend/requirements.txt`
```
modal==0.64.*
boto3>=1.34
```
*(Everything training-side — `torch`, `transformers`, `peft`, `trl`, `datasets` — lives inside the Modal container image, NOT in our backend requirements.)*

---

## File 1 · `/app/backend/training/__init__.py`

Empty. Just marks the package.

---

## File 2 · `/app/backend/training/storage.py`

Purpose: thin R2/S3 client. One place to swap providers.

```python
"""R2 object storage adapter (S3-compatible)."""
from __future__ import annotations
import os
from typing import Optional
import boto3
from botocore.client import Config

_client = None

def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _client

def bucket() -> str:
    return os.environ["R2_BUCKET"]

def put_bytes(key: str, data: bytes, content_type: str = "application/json") -> str:
    """Upload bytes to R2. Returns the public URL."""
    client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"

def put_stream(key: str, iterator, content_type: str = "application/x-ndjson") -> str:
    """Upload a streaming iterator (for large JSONL). Buffers into memory —
    training exports are ~10MB max so this is fine. Rewrite as multipart if
    exports ever exceed 100MB."""
    buf = b"".join(chunk.encode() if isinstance(chunk, str) else chunk for chunk in iterator)
    return put_bytes(key, buf, content_type)

def presign_get(key: str, expires: int = 3600) -> str:
    """Generate a time-limited GET URL. Modal reads datasets via this."""
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket(), "Key": key},
        ExpiresIn=expires,
    )
```

### Test
```
python -c "from backend.training.storage import put_bytes; print(put_bytes('test/hello.txt', b'hi'))"
```
Should print the public URL. Fetch it with curl to verify.

---

## File 3 · `/app/backend/training/exporter.py`

Purpose: turn Mongo rows into training-shaped JSONL and stash on R2.
Called by the `POST /api/training/datasets` route (currently a stub — you'll
wire it in File 8).

```python
"""SFT + DPO exporters. Mongo → JSONL → R2."""
from __future__ import annotations
import io
import json
from datetime import datetime, timezone
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from .storage import put_bytes


async def export_sft(db: AsyncIOMotorDatabase, dataset_id: str,
                    row_limit: int = 5000,
                    date_from: Optional[str] = None,
                    date_to: Optional[str] = None,
                    domains: Optional[list[str]] = None) -> dict:
    """Chronicle ai_answer rows with verdict=pass → SFT JSONL.
    Returns {row_count, size_bytes, download_url}.
    """
    q: dict = {"kind": "ai_answer", "body.verdict": "pass"}
    if date_from: q.setdefault("ts", {})["$gte"] = date_from
    if date_to:   q.setdefault("ts", {})["$lte"] = date_to
    if domains:   q["body.scope"] = {"$in": domains}

    buf = io.BytesIO()
    row_count = 0
    async for doc in db.chronicle_entries.find(q, {"_id": 0}).limit(row_limit):
        body = doc.get("body", {})
        prompt = body.get("prompt")
        response = body.get("response")
        if not prompt or not response:
            continue
        row = {
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ],
            "meta": {
                "chronicle_id": doc.get("id"),
                "model": body.get("model"),
                "verdict": body.get("verdict"),
                "ts": doc.get("ts"),
            },
        }
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        row_count += 1

    data = buf.getvalue()
    key = f"datasets/{dataset_id}.sft.jsonl"
    url = put_bytes(key, data, content_type="application/x-ndjson")
    return {"row_count": row_count, "size_bytes": len(data), "download_url": url,
            "s3_key": key}


async def export_dpo(db: AsyncIOMotorDatabase, dataset_id: str,
                    row_limit: int = 5000,
                    only_approved: bool = True) -> dict:
    """knowledge_dpo_candidates → DPO JSONL.
    only_approved=True means we skip candidates that haven't been triaged in
    the reviewer. Set False for the exploratory 'stash everything' export.
    """
    q: dict = {}
    if only_approved:
        q["status"] = "approved"

    buf = io.BytesIO()
    row_count = 0
    async for doc in db.knowledge_dpo_candidates.find(q, {"_id": 0}).limit(row_limit):
        fact = await db.knowledge_facts.find_one(
            {"id": doc.get("chosen_fact_id")}, {"_id": 0, "title": 1, "body": 1})
        if not fact:
            continue
        chosen = f"{fact.get('title','')}\n\n{fact.get('body','')}".strip()
        rejected = f"{doc.get('rejected_title','')}\n\n{doc.get('rejected_body','')}".strip()
        if not chosen or not rejected:
            continue
        row = {
            "prompt": doc.get("query", ""),
            "chosen": chosen,
            "rejected": rejected,
            "meta": {
                "dpo_id": doc.get("id"),
                "category": doc.get("category"),
                "reject_reason": doc.get("reject_reason"),
                "ts": doc.get("ts"),
            },
        }
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        row_count += 1

    data = buf.getvalue()
    key = f"datasets/{dataset_id}.dpo.jsonl"
    url = put_bytes(key, data, content_type="application/x-ndjson")
    return {"row_count": row_count, "size_bytes": len(data), "download_url": url,
            "s3_key": key}
```

### Test
Add `/app/backend/tests/test_exporter.py`:
```python
import pytest, asyncio
from deps import db
from backend.training.exporter import export_sft, export_dpo

@pytest.mark.asyncio
async def test_sft_export_produces_valid_jsonl():
    result = await export_sft(db, dataset_id="test_sft_001", row_limit=10)
    assert result["row_count"] >= 0
    assert result["download_url"].startswith("https://")

@pytest.mark.asyncio
async def test_dpo_export_only_approved():
    result = await export_dpo(db, dataset_id="test_dpo_001", only_approved=True)
    assert result["row_count"] >= 0
```

---

## File 4 · `/app/backend/training/modal_client.py`

Purpose: dispatch a run to Modal, cancel a run, poll status.

```python
"""Modal dispatch shim. Zero heavy imports at module-load time — Modal SDK
is expensive to import so we lazy-load inside functions."""
from __future__ import annotations
import os
from typing import Optional


def _app():
    """Lazy import Modal SDK. Raises if credentials missing."""
    import modal  # type: ignore
    return modal.App.lookup(
        os.environ.get("MODAL_APP_NAME", "j-training"),
        create_if_missing=False,
    )


def dispatch(run_id: str,
             base_model: str,
             training_method: str,       # "sft" | "dpo"
             dataset_url: str,           # presigned GET on R2
             lora_rank: int,
             learning_rate: float,
             epochs: int,
             batch_size: int,
             webhook_url: str,
             webhook_secret: str) -> str:
    """Spawn a training task on Modal. Returns the modal_task_id."""
    import modal  # type: ignore
    fn = modal.Function.lookup("j-training", "train")
    call = fn.spawn(
        run_id=run_id,
        base_model=base_model,
        training_method=training_method,
        dataset_url=dataset_url,
        lora_rank=lora_rank,
        learning_rate=learning_rate,
        epochs=epochs,
        batch_size=batch_size,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )
    return call.object_id


def cancel(modal_task_id: str) -> bool:
    import modal  # type: ignore
    try:
        call = modal.FunctionCall.from_id(modal_task_id)
        call.cancel()
        return True
    except Exception:
        return False
```

### Test
Pure integration — smoke-test only when Modal creds are present:
```python
def test_dispatch_signature():
    # Just verify import works; skip actual dispatch if MODAL_TOKEN_ID unset.
    import os
    if not os.environ.get("MODAL_TOKEN_ID"):
        pytest.skip("no modal creds")
    from backend.training.modal_client import dispatch
    assert callable(dispatch)
```

---

## File 5 · `/app/backend/training/train.py`  ← LIVES IN THE MODAL CONTAINER

Purpose: the actual training script. Deployed to Modal via `modal deploy`,
not part of our runtime backend. Keep it here in the repo for versioning.

```python
"""Modal training image + entrypoint. Deploy with:
    modal deploy backend/training/train.py

This file is NOT imported by our FastAPI backend. It runs inside a GPU
container on Modal. Everything below `@app.function` executes remotely.
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.4.0",
        "transformers==4.44.0",
        "peft==0.12.0",
        "trl==0.9.6",
        "datasets==2.20.0",
        "accelerate==0.33.0",
        "bitsandbytes==0.43.3",
        "safetensors==0.4.4",
        "boto3>=1.34",
        "httpx>=0.27",
    )
)

app = modal.App("j-training", image=image)
volume = modal.Volume.from_name("hf-cache", create_if_missing=True)

BASE_MODEL_MAP = {
    "qwen2.5-coder-7b":       "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen2.5-14b-instruct":   "Qwen/Qwen2.5-14B-Instruct",
    "llama-3.1-8b-instruct":  "meta-llama/Llama-3.1-8B-Instruct",
    "mistral-7b-v0.3":        "mistralai/Mistral-7B-v0.3",
}


@app.function(
    gpu="A100",           # A100-40GB for 7B; bump to "A100-80GB" for 14B
    timeout=3600 * 3,     # 3 hours max per run
    volumes={"/root/.cache/huggingface": volume},
    secrets=[modal.Secret.from_name("r2-creds")],
)
def train(run_id: str, base_model: str, training_method: str,
          dataset_url: str, lora_rank: int, learning_rate: float,
          epochs: int, batch_size: int,
          webhook_url: str, webhook_secret: str) -> dict:
    """Fine-tune a base model with LoRA. Post progress webhooks. Upload
    adapter to R2. Post final completion webhook."""
    import os, json, time, hmac, hashlib, tempfile, boto3, httpx
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model
    from datasets import load_dataset

    def post_webhook(payload: dict):
        sig = hmac.new(webhook_secret.encode(), json.dumps(payload).encode(),
                       hashlib.sha256).hexdigest()
        try:
            httpx.post(webhook_url, json=payload,
                       headers={"X-Modal-Signature": sig}, timeout=15)
        except Exception:
            pass  # never let webhook failure abort training

    hf_id = BASE_MODEL_MAP.get(base_model)
    if not hf_id:
        post_webhook({"run_id": run_id, "status": "failed",
                      "error": f"unknown base_model={base_model}"})
        return {"ok": False}

    post_webhook({"run_id": run_id, "status": "running", "step": 0,
                  "message": f"Pulling {hf_id}"})

    tokenizer = AutoTokenizer.from_pretrained(hf_id)
    model = AutoModelForCausalLM.from_pretrained(
        hf_id, torch_dtype="bfloat16", device_map="auto",
    )
    peft_cfg = LoraConfig(
        r=lora_rank, lora_alpha=lora_rank * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, peft_cfg)

    # Download dataset from R2
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        f.write(httpx.get(dataset_url, timeout=120).content)
        dataset_path = f.name
    ds = load_dataset("json", data_files=dataset_path, split="train")

    if training_method == "sft":
        from trl import SFTConfig, SFTTrainer
        cfg = SFTConfig(
            output_dir=f"/tmp/{run_id}", num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=learning_rate, logging_steps=10,
            save_strategy="no", report_to="none", bf16=True,
        )
        trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                             tokenizer=tokenizer)
    elif training_method == "dpo":
        from trl import DPOConfig, DPOTrainer
        cfg = DPOConfig(
            output_dir=f"/tmp/{run_id}", num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=learning_rate, logging_steps=10,
            save_strategy="no", report_to="none", bf16=True, beta=0.1,
        )
        trainer = DPOTrainer(model=model, args=cfg, train_dataset=ds,
                             tokenizer=tokenizer)
    else:
        post_webhook({"run_id": run_id, "status": "failed",
                      "error": f"unknown training_method={training_method}"})
        return {"ok": False}

    # Progress webhooks via a custom callback
    from transformers import TrainerCallback
    class WebhookCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if not logs: return
            post_webhook({
                "run_id": run_id, "status": "running",
                "step": state.global_step,
                "loss": logs.get("loss") or logs.get("train_loss"),
                "epoch": logs.get("epoch"),
            })
    trainer.add_callback(WebhookCallback())

    trainer.train()

    # Save adapter and upload to R2
    adapter_dir = f"/tmp/{run_id}-adapter"
    model.save_pretrained(adapter_dir)
    s3 = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    for fname in os.listdir(adapter_dir):
        s3.upload_file(f"{adapter_dir}/{fname}",
                       os.environ["R2_BUCKET"],
                       f"adapters/{run_id}/{fname}")
    adapter_url = f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/adapters/{run_id}/"

    post_webhook({
        "run_id": run_id, "status": "complete", "adapter_url": adapter_url,
        "final_loss": float(trainer.state.log_history[-1].get("train_loss", 0)),
    })
    return {"ok": True, "adapter_url": adapter_url}
```

### Deploy step (one-time + on every change to this file)
```
cd /app
modal secret create r2-creds R2_ENDPOINT=$R2_ENDPOINT R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY R2_BUCKET=$R2_BUCKET R2_PUBLIC_URL=$R2_PUBLIC_URL
modal deploy backend/training/train.py
```

---

## File 6 · `/app/backend/routes/training_webhooks.py`

Purpose: receive progress + completion callbacks from Modal.

```python
"""Modal → backend webhook. HMAC-signed, mounted at /api/training/webhook."""
from __future__ import annotations
import hmac, hashlib, os, json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request

from deps import db

router = APIRouter()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/training/webhook")
async def modal_webhook(request: Request):
    secret = os.environ.get("TRAINING_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="webhook_disabled")

    body = await request.body()
    sig = request.headers.get("X-Modal-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="bad_signature")

    payload = json.loads(body)
    run_id = payload.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")

    status = payload.get("status")
    update: dict = {}

    if status == "running":
        update["status"] = "running"
        if payload.get("loss") is not None:
            update["$push"] = {
                "loss_history": {
                    "step": payload.get("step"),
                    "loss": payload.get("loss"),
                    "epoch": payload.get("epoch"),
                    "ts": _now(),
                }
            }
    elif status == "complete":
        update["status"] = "complete"
        update["completed_at"] = _now()
        update["adapter_url"] = payload.get("adapter_url")
        update["final_loss"] = payload.get("final_loss")
    elif status == "failed":
        update["status"] = "failed"
        update["completed_at"] = _now()
        update["error"] = payload.get("error")

    if not update:
        return {"ok": True, "no_op": True}

    # Split $push out of $set
    push = update.pop("$push", None)
    ops: dict = {}
    if update:
        ops["$set"] = update
    if push:
        ops["$push"] = push
    await db.training_runs.update_one({"run_id": run_id}, ops)

    # Fire activity feed
    if status in ("complete", "failed"):
        await db.training_events.insert_one({
            "event_id": f"evt_{run_id}_{status}",
            "type": f"run.{status}",
            "message": f"Run {run_id} {status}"
                       + (f": {payload.get('error')}" if status == 'failed' else ""),
            "run_id": run_id,
            "ts": _now(),
        })

    return {"ok": True}
```

Wire into `/app/backend/server.py`:
```python
from routes import training_webhooks
api.include_router(training_webhooks.router)
```

### Test
```
API=<preview>
SECRET=<from .env>
BODY='{"run_id":"r_test","status":"running","step":10,"loss":0.5}'
SIG=$(python3 -c "import hmac,hashlib,sys; print(hmac.new(b'$SECRET',b'''$BODY''',hashlib.sha256).hexdigest())")
curl -X POST $API/api/training/webhook -H "X-Modal-Signature: $SIG" -H "Content-Type: application/json" -d "$BODY"
```

---

## File 7 · `/app/backend/training/eval_runner.py`

Purpose: after a run completes, replay `golden.jsonl` through it, run Five
Masters on each output, compute pass-rate + delta vs champion.

```python
"""Golden-set eval. Reads /app/backend/tests/eval/golden.jsonl, sends every
prompt through model_a and model_b, runs Five Masters + heuristic scorers on
each output, computes deltas.

Model resolution:
  - "champion"   → whichever training_models row has is_current_champion=True
  - "base:<id>"  → dispatch to the base model through llm_chain
  - "<model_id>" → look up training_models by model_id, use its adapter
"""
from __future__ import annotations
import json, asyncio
from datetime import datetime, timezone
from pathlib import Path

from deps import db
from core.fivemasters import evaluate_python  # existing AST evaluator

GOLDEN_PATH = Path("/app/backend/tests/eval/golden.jsonl")


async def run_eval(eval_id: str, model_a: str, model_b: str) -> dict:
    """Update the training_evals row as we go — the frontend polls it."""
    prompts = [json.loads(l) for l in GOLDEN_PATH.read_text().splitlines() if l.strip()]
    total = len(prompts)
    await db.training_evals.update_one(
        {"eval_id": eval_id},
        {"$set": {"status": "running",
                  "progress": {"completed": 0, "total": total}}},
    )

    items = []
    a_passes = b_passes = 0
    for i, p in enumerate(prompts):
        ans_a = await _generate(model_a, p["prompt"])
        ans_b = await _generate(model_b, p["prompt"])
        # For code prompts, Five Masters AST check
        if p.get("expects") == "code":
            fm_a = evaluate_python(ans_a).get("passed", False)
            fm_b = evaluate_python(ans_b).get("passed", False)
        else:
            fm_a = _string_match(ans_a, p.get("must_contain", []))
            fm_b = _string_match(ans_b, p.get("must_contain", []))
        a_passes += int(fm_a)
        b_passes += int(fm_b)
        items.append({
            "prompt": p["prompt"], "a_answer": ans_a, "b_answer": ans_b,
            "a_pass": fm_a, "b_pass": fm_b,
        })
        await db.training_evals.update_one(
            {"eval_id": eval_id},
            {"$set": {"progress": {"completed": i + 1, "total": total}}},
        )

    summary = {
        "a_score": round(a_passes / total, 3),
        "b_score": round(b_passes / total, 3),
        "delta":   round((b_passes - a_passes) / total, 3),
    }
    await db.training_evals.update_one(
        {"eval_id": eval_id},
        {"$set": {"status": "complete", "summary": summary, "items": items,
                  "completed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return summary


def _string_match(text: str, needles: list[str]) -> bool:
    return all(n.lower() in (text or "").lower() for n in needles)


async def _generate(model_ref: str, prompt: str) -> str:
    """Resolve model_ref → adapter or base → single-turn generation.
    For MVP, route non-adapter refs through the existing `llm_chain` and
    treat trained adapters as a special provider that spawns a short-lived
    Modal call to run inference against the adapter."""
    if model_ref.startswith("base:") or model_ref == "champion":
        # Fallback: call our existing chat chain
        from core.llm_chain import chat_once  # exposes the chain synchronously
        return await chat_once(prompt=prompt, user_id="eval_bot")
    # trained model — call Modal inference function (build in a follow-up)
    from .modal_client import _app  # noqa
    # placeholder for MVP: return a stub. Wire the real adapter-inference call
    # once train.py exposes an `@app.function def infer(...)` endpoint.
    return f"[unimplemented adapter inference for {model_ref}]"
```

### Test
Integration test only — depends on real generation. Skip in CI:
```python
@pytest.mark.skipif(not os.environ.get("EVAL_LIVE"), reason="live eval")
async def test_eval_runs_end_to_end():
    from backend.training.eval_runner import run_eval
    r = await run_eval("ev_test", "base:qwen2.5-coder-7b", "champion")
    assert "a_score" in r
```

---

## File 8 · Wire `training.py` stubs to the real implementations

Purpose: patch the existing stubs to call the real code.

### Diff `/app/backend/routes/training.py`

**In `create_dataset`**, replace the TODO block with:
```python
# Dispatch to exporter in the background (fire-and-forget).
import asyncio
from backend.training.exporter import export_sft, export_dpo
async def _run():
    try:
        exporter = export_sft if fmt == "sft" else export_dpo
        result = await exporter(db, dataset_id, row_limit=doc["row_limit"])
        await db.training_datasets.update_one(
            {"id": dataset_id},
            {"$set": {"status": "ready", "row_count": result["row_count"],
                      "size_mb": round(result["size_bytes"] / (1024*1024), 3),
                      "download_url": result["download_url"]}},
        )
    except Exception as e:
        await db.training_datasets.update_one(
            {"id": dataset_id},
            {"$set": {"status": "failed", "error": str(e)}},
        )
asyncio.create_task(_run())
```

**In `create_run`**, replace the TODO with:
```python
from backend.training.modal_client import dispatch
from backend.training.storage import presign_get
try:
    ds_url = presign_get(f"datasets/{dataset_id}.{doc['training_method']}.jsonl")
    task_id = dispatch(
        run_id=run_id,
        base_model=doc["base_model"],
        training_method=doc["training_method"],
        dataset_url=ds_url,
        lora_rank=doc["lora_rank"],
        learning_rate=doc["learning_rate"],
        epochs=doc["epochs"],
        batch_size=doc["batch_size"],
        webhook_url=f"{os.environ['PUBLIC_BACKEND_URL']}/api/training/webhook",
        webhook_secret=os.environ["TRAINING_WEBHOOK_SECRET"],
    )
    await db.training_runs.update_one(
        {"run_id": run_id},
        {"$set": {"modal_task_id": task_id, "status": "running"}},
    )
except Exception as e:
    await db.training_runs.update_one(
        {"run_id": run_id},
        {"$set": {"status": "failed", "error": f"dispatch: {e}"}},
    )
```

**In `cancel_run`**, add before the DB update:
```python
if doc.get("modal_task_id"):
    from backend.training.modal_client import cancel
    cancel(doc["modal_task_id"])
```

**In `promote_run` / `_promote_model_by_id`**, replace the `TODO: reload
llm_chain TASK_CHAINS` comment with:
```python
from core.llm_chain import invalidate_champion_cache
invalidate_champion_cache()
```

---

## File 9 · `/app/backend/core/llm_chain.py` — champion lookup

Purpose: teach the chain how to route through a promoted adapter.

Add at module scope:
```python
_CHAMPION_CACHE: dict = {"model_id": None, "adapter_url": None, "ts": 0}
_CHAMPION_TTL = 60  # seconds


async def _resolve_champion() -> Optional[dict]:
    """Cached read of the current champion. Cheap to call on every chain resolve."""
    import time
    now = time.time()
    if now - _CHAMPION_CACHE["ts"] < _CHAMPION_TTL and _CHAMPION_CACHE["model_id"]:
        return _CHAMPION_CACHE
    from deps import db
    row = await db.training_models.find_one(
        {"is_current_champion": True},
        {"_id": 0, "model_id": 1, "adapter_url": 1, "base_model": 1},
    )
    if row:
        _CHAMPION_CACHE.update({
            "model_id": row["model_id"],
            "adapter_url": row.get("adapter_url"),
            "base_model": row.get("base_model"),
            "ts": now,
        })
    return _CHAMPION_CACHE if _CHAMPION_CACHE["model_id"] else None


def invalidate_champion_cache():
    _CHAMPION_CACHE["ts"] = 0
```

Wire into `resolve_chain()`:
```python
async def resolve_chain(task: str, user_id: str) -> list[dict]:
    champ = await _resolve_champion()
    chain = list(TASK_CHAINS.get(task, []))  # existing static chain
    if champ:
        # Prepend the champion adapter as the first step
        chain.insert(0, {
            "provider": "modal-adapter",
            "model": champ["model_id"],
            "adapter_url": champ["adapter_url"],
            "base_model": champ["base_model"],
        })
    return chain
```

Also add a `modal-adapter` branch in the chain executor to call a Modal
`infer` function (build alongside `train.py`).

---

## Wire order — do NOT skip

1. Add env vars → restart backend → smoke-test with `curl /api/training/health` (should show `modal_configured:true, storage_configured:true`).
2. Write File 2 (storage), File 3 (exporter). Run pytest.
3. Write File 4 (modal_client), File 5 (train.py). `modal deploy`.
4. Write File 6 (webhooks). Wire into `server.py`. Fake-webhook curl test.
5. Wire File 8 patches into `routes/training.py`. Trigger a dataset from the bolt UI. Watch it flip to `status:ready`.
6. Kick a training run from bolt. Watch webhooks land in Mongo. Verify adapter appears in R2.
7. Write File 9 champion-cache logic. Promote a model from bolt. `curl /api/ai/chain` and verify the adapter shows up as the first step.
8. Write File 7 (eval_runner). Run one eval end-to-end.

---

## What breaks if you skip a step

- **Skip File 2** → File 3 fails at import (`from .storage import put_bytes`).
- **Skip File 5 deploy** → File 4 `dispatch` throws `NotFoundError` from Modal.
- **Skip File 6** → Runs stay stuck at `status:queued` forever because nothing writes progress back.
- **Skip File 9** → Promotion works in DB but J still uses the old chain in memory.

---

## Cost & scale reality check

- 7B LoRA on 1000 SFT rows @ 3 epochs on A100-40GB: ~30 min, ~$1.50.
- 14B DPO on 500 pairs @ 2 epochs on A100-80GB: ~1 hour, ~$5.
- R2 storage: adapter ~200MB × 20 runs = 4GB → $0.06/mo.
- Cloudflare R2 egress is FREE (this is why we chose R2 over S3).

Nightly SFT budget under $50/mo covers ~30 runs. Comfortable.
