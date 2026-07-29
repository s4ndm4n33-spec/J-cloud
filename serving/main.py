"""Cerebrium serving entry — LoRA adapter inference on Cloudflare R2 artefacts.

The `predict` function is what Cerebrium exposes as an HTTP endpoint. It:

  1. Loads a base model (Qwen 2.5 / Llama 3.1) once per replica, in 4bit
     with bitsandbytes. Cached in-memory across requests.
  2. Downloads a LoRA adapter tarball (or directory of shards) from R2
     under `adapters/{run_id}/`, extracts to /tmp, applies with PEFT.
     Adapter combinations are cached (bounded LRU).
  3. Runs generate() with the user's prompt and returns text + timing.

Everything is per-request-parameterised so a single deployed replica can
serve many different fine-tuned J variants without redeploys.

Request payload:
    {
      "prompt":       "<user turn>",
      "base_model":   "qwen2.5-coder-7b" | "qwen2.5-14b-instruct" | "llama-3.1-8b-instruct",
      "run_id":       "<training_runs.run_id>"          # locates adapter in R2
      "max_new_tokens": 512,                            # optional, default 512
      "temperature":  0.7,                              # optional
      "top_p":        0.9,                              # optional
      "system":       "<optional system prompt>",       # optional
    }

Response:
    {
      "ok":       true,
      "text":     "<J's reply>",
      "usage":    {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N},
      "timing_ms": {"load_base": ..., "load_adapter": ..., "generate": ...}
    }
"""
from __future__ import annotations

import io
import os
import tarfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import boto3
import torch
from botocore.client import Config as BotoConfig
from pydantic import BaseModel, Field
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM, AutoTokenizer,
    BitsAndBytesConfig, TextIteratorStreamer,
)

# ---------------------------------------------------------------------------
# Base-model registry — must stay aligned with backend/training/train.py so
# adapters produced by that pipeline load without a version dance.
# ---------------------------------------------------------------------------

BASE_MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder-7b":      "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen2.5-14b-instruct":  "Qwen/Qwen2.5-14B-Instruct",
    "llama-3.1-8b-instruct": "meta-llama/Llama-3.1-8B-Instruct",
}

# In-memory caches. Cerebrium replicas persist between requests, so
# amortising load cost across the replica's lifetime is a real win.
_BASE_CACHE: dict[str, tuple] = {}                  # base_model_id -> (model, tokenizer)
_ADAPTER_CACHE: "OrderedDict[str, PeftModel]" = OrderedDict()
_ADAPTER_CACHE_MAX = 4                              # LRU cap — depends on host memory


# ---------------------------------------------------------------------------
# R2 (S3-compatible) helpers
# ---------------------------------------------------------------------------

def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


def _download_adapter(run_id: str) -> Path:
    """Pull an adapter's files from R2 under `adapters/{run_id}/` into a
    local dir. If the trainer wrote a single `adapter.tar.gz` we extract
    it; otherwise we mirror the prefix's individual files (peft's expected
    layout: adapter_config.json + adapter_model.safetensors + tokenizer_*).
    """
    dest = Path("/tmp/adapters") / run_id
    if dest.exists() and any(dest.iterdir()):
        return dest
    dest.mkdir(parents=True, exist_ok=True)

    bucket = os.environ["R2_BUCKET"]
    prefix = f"adapters/{run_id}/"
    s3 = _r2_client()

    # Prefer tarball if present — one round-trip, atomic.
    tar_key = f"{prefix}adapter.tar.gz"
    try:
        obj = s3.get_object(Bucket=bucket, Key=tar_key)
        with tarfile.open(fileobj=io.BytesIO(obj["Body"].read()), mode="r:gz") as tf:
            try:
                tf.extractall(dest, filter="data")
            except TypeError:
                tf.extractall(dest)  # stdlib pre-3.12 fallback
        return dest
    except s3.exceptions.NoSuchKey:
        pass  # fall through to per-file mirror
    except Exception:
        pass

    # Fallback — list + fetch every object under the prefix.
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []) or []:
            key = item["Key"]
            rel = key[len(prefix):]
            if not rel:
                continue
            local = dest / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(local))

    if not any(dest.iterdir()):
        raise FileNotFoundError(f"no adapter files found at r2://{bucket}/{prefix}")
    return dest


# ---------------------------------------------------------------------------
# Model / adapter loaders
# ---------------------------------------------------------------------------

def _load_base(base_model_id: str) -> tuple:
    """Load a base model in 4bit. Cached per replica lifetime."""
    if base_model_id in _BASE_CACHE:
        return _BASE_CACHE[base_model_id]
    hf_id = BASE_MODEL_MAP.get(base_model_id)
    if not hf_id:
        raise ValueError(f"unknown base_model: {base_model_id}. "
                         f"Known: {list(BASE_MODEL_MAP)}")

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )
    tok = AutoTokenizer.from_pretrained(hf_id, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        hf_id,
        quantization_config=bnb,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.eval()
    _BASE_CACHE[base_model_id] = (model, tok)
    return model, tok


def _load_with_adapter(base_model_id: str, run_id: str) -> tuple:
    """Return a (peft_model, tokenizer) with the requested adapter applied.
    LRU-cached per (base, run_id) combo so repeat calls skip the load cost.
    """
    cache_key = f"{base_model_id}::{run_id}"
    if cache_key in _ADAPTER_CACHE:
        _ADAPTER_CACHE.move_to_end(cache_key)  # LRU bump
        return _ADAPTER_CACHE[cache_key], _BASE_CACHE[base_model_id][1]

    base, tok = _load_base(base_model_id)
    adapter_dir = _download_adapter(run_id)
    peft_model = PeftModel.from_pretrained(base, str(adapter_dir))
    peft_model.eval()

    _ADAPTER_CACHE[cache_key] = peft_model
    while len(_ADAPTER_CACHE) > _ADAPTER_CACHE_MAX:
        _ADAPTER_CACHE.popitem(last=False)  # evict oldest
    return peft_model, tok


# ---------------------------------------------------------------------------
# Request schema + entry point
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    base_model: str = Field(..., description="key from BASE_MODEL_MAP")
    run_id: str = Field(..., min_length=1, description="training_runs.run_id — locates adapter in R2")
    max_new_tokens: int = Field(512, ge=1, le=4096)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    system: Optional[str] = None


def _apply_chat_template(tok, system: Optional[str], prompt: str) -> str:
    """Use the tokenizer's own chat template when available (Qwen/Llama
    ship theirs). Falls back to a minimal `[SYS]/[USR]` wrapper otherwise."""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    if getattr(tok, "chat_template", None):
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    parts = [f"[SYS]\n{system}\n[/SYS]"] if system else []
    parts.append(f"[USR]\n{prompt}\n[/USR]\n[ASSISTANT]\n")
    return "\n".join(parts)


def predict(item: dict) -> dict:
    """Cerebrium's entry point. Validates, loads, generates, returns."""
    req = PredictRequest.model_validate(item)
    timing: dict[str, float] = {}

    t0 = time.perf_counter()
    model, tok = _load_with_adapter(req.base_model, req.run_id)
    timing["load_total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    text_in = _apply_chat_template(tok, req.system, req.prompt)
    inputs = tok(text_in, return_tensors="pt").to(model.device)
    prompt_tokens = int(inputs["input_ids"].shape[1])

    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=req.max_new_tokens,
            do_sample=req.temperature > 0,
            temperature=req.temperature if req.temperature > 0 else 1.0,
            top_p=req.top_p,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
        )
    timing["generate_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    completion_ids = out[0, prompt_tokens:]
    completion_tokens = int(completion_ids.shape[0])
    text = tok.decode(completion_ids, skip_special_tokens=True)

    return {
        "ok": True,
        "text": text,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "timing_ms": timing,
        "cache": {
            "base_loaded": list(_BASE_CACHE.keys()),
            "adapters_cached": list(_ADAPTER_CACHE.keys()),
        },
    }


def health() -> dict:
    """Optional Cerebrium `health` route — cheap probe used by the backend
    to verify the endpoint is reachable + secrets are wired."""
    return {
        "ok": True,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "r2_configured": all(k in os.environ for k in (
            "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
        )),
        "known_base_models": list(BASE_MODEL_MAP.keys()),
        "base_loaded": list(_BASE_CACHE.keys()),
        "adapters_cached": list(_ADAPTER_CACHE.keys()),
    }
