"""Modal training image + entrypoints.

Deploy this file to Modal (not to our FastAPI backend):
    cd /app/backend && modal deploy training/train.py

Once deployed, the FastAPI backend calls `train.spawn(...)` from
`modal_client.py`. This file itself is never imported by uvicorn — it
runs inside GPU containers on Modal's infrastructure.

Contains two functions:
- `smoke_test`: CPU-only, ~5s, no HF pull, no cost. For plumbing checks.
- `train`: A100 GPU, LoRA fine-tune Qwen 2.5 Coder 7B or Llama 3.1 8B.

Progress + completion → HMAC-signed webhook to PUBLIC_BACKEND_URL.
"""
import modal

# ---------------------------------------------------------------------------
# Image — heavy deps ONLY inside this container. Never in backend/requirements.
# ---------------------------------------------------------------------------
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
        "sentencepiece==0.2.0",
        "rich>=13.0",
        "boto3>=1.34",
        "httpx>=0.27",
    )
)

app = modal.App("j-training", image=image)
hf_volume = modal.Volume.from_name("hf-cache", create_if_missing=True)

BASE_MODEL_MAP = {
    "qwen2.5-coder-7b":     "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen2.5-14b-instruct": "Qwen/Qwen2.5-14B-Instruct",
    "llama-3.1-8b-instruct": "meta-llama/Llama-3.1-8B-Instruct",
    "mistral-7b-v0.3":      "mistralai/Mistral-7B-v0.3",
}


# ---------------------------------------------------------------------------
# Smoke test — proves the plumbing works without a $2 GPU spin-up.
# ---------------------------------------------------------------------------
@app.function(cpu=1, timeout=60)
def smoke_test(run_id: str, webhook_url: str, webhook_secret: str) -> dict:
    """Just sends a fake progress + completion webhook. Used to verify the
    end-to-end dispatch → webhook loop before spending real training $$$."""
    import hmac, hashlib, json, time, httpx

    def _post(payload: dict):
        body = json.dumps(payload).encode()
        sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            httpx.post(webhook_url, content=body,
                       headers={"X-Modal-Signature": sig,
                                "Content-Type": "application/json"},
                       timeout=15)
        except Exception:
            pass

    _post({"run_id": run_id, "status": "running", "step": 0,
           "message": "smoke test started"})
    time.sleep(2)
    for step, loss in [(10, 1.2), (20, 0.9), (30, 0.6)]:
        _post({"run_id": run_id, "status": "running",
               "step": step, "loss": loss, "epoch": 1})
        time.sleep(1)
    _post({"run_id": run_id, "status": "complete",
           "adapter_url": "https://example.invalid/smoke-test-adapter",
           "final_loss": 0.6, "smoke_test": True})
    return {"ok": True, "run_id": run_id}


# ---------------------------------------------------------------------------
# Real training — A100, LoRA, SFT or DPO.
# ---------------------------------------------------------------------------
@app.function(
    gpu="A100",
    timeout=60 * 60 * 3,  # 3 hours cap
    volumes={"/root/.cache/huggingface": hf_volume},
    secrets=[modal.Secret.from_name("r2-credentials")],
)
def train(run_id: str,
          base_model: str,
          training_method: str,        # "sft" | "dpo"
          dataset_url: str,            # presigned R2 GET
          lora_rank: int,
          learning_rate: float,
          epochs: int,
          batch_size: int,
          webhook_url: str,
          webhook_secret: str) -> dict:
    import os, json, time, hmac, hashlib, tempfile, boto3, httpx

    def _post(payload: dict):
        body = json.dumps(payload).encode()
        sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            httpx.post(webhook_url, content=body,
                       headers={"X-Modal-Signature": sig,
                                "Content-Type": "application/json"}, timeout=15)
        except Exception:
            pass

    hf_id = BASE_MODEL_MAP.get(base_model)
    if not hf_id:
        _post({"run_id": run_id, "status": "failed",
               "error": f"unknown base_model={base_model}"})
        return {"ok": False}

    try:
        _post({"run_id": run_id, "status": "running", "step": 0,
               "message": f"Pulling {hf_id}"})

        from transformers import AutoTokenizer, AutoModelForCausalLM
        from peft import LoraConfig, get_peft_model
        from datasets import load_dataset
        import torch

        tokenizer = AutoTokenizer.from_pretrained(hf_id)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            hf_id, torch_dtype=torch.bfloat16, device_map="auto")
        peft_cfg = LoraConfig(
            r=lora_rank, lora_alpha=lora_rank * 2, lora_dropout=0.05,
            bias="none", task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        )
        model = get_peft_model(model, peft_cfg)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            f.write(httpx.get(dataset_url, timeout=120, follow_redirects=True).content)
            dataset_path = f.name
        ds = load_dataset("json", data_files=dataset_path, split="train")

        from transformers import TrainerCallback

        class WebhookCB(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                if not logs: return
                _post({"run_id": run_id, "status": "running",
                       "step": state.global_step,
                       "loss": logs.get("loss") or logs.get("train_loss"),
                       "epoch": logs.get("epoch")})

        if training_method == "sft":
            from trl import SFTConfig, SFTTrainer
            cfg = SFTConfig(
                output_dir=f"/tmp/{run_id}", num_train_epochs=epochs,
                per_device_train_batch_size=batch_size,
                learning_rate=learning_rate, logging_steps=5,
                save_strategy="no", report_to="none", bf16=True,
            )
            trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                                 tokenizer=tokenizer, callbacks=[WebhookCB()])
        elif training_method == "dpo":
            from trl import DPOConfig, DPOTrainer
            cfg = DPOConfig(
                output_dir=f"/tmp/{run_id}", num_train_epochs=epochs,
                per_device_train_batch_size=batch_size,
                learning_rate=learning_rate, logging_steps=5,
                save_strategy="no", report_to="none", bf16=True, beta=0.1,
            )
            trainer = DPOTrainer(model=model, args=cfg, train_dataset=ds,
                                 tokenizer=tokenizer, callbacks=[WebhookCB()])
        else:
            _post({"run_id": run_id, "status": "failed",
                   "error": f"unknown training_method={training_method}"})
            return {"ok": False}

        trainer.train()

        adapter_dir = f"/tmp/{run_id}-adapter"
        model.save_pretrained(adapter_dir)

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        for fname in os.listdir(adapter_dir):
            s3.upload_file(f"{adapter_dir}/{fname}",
                           os.environ["R2_BUCKET"],
                           f"adapters/{run_id}/{fname}")
        adapter_url = f"s3://{os.environ['R2_BUCKET']}/adapters/{run_id}/"

        final_loss = float(trainer.state.log_history[-1].get("train_loss", 0))
        _post({"run_id": run_id, "status": "complete",
               "adapter_url": adapter_url, "final_loss": final_loss})
        return {"ok": True, "adapter_url": adapter_url}

    except Exception as e:
        _post({"run_id": run_id, "status": "failed", "error": str(e)[:500]})
        raise
