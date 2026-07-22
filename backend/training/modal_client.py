"""Modal dispatch shim used by the FastAPI backend.

Lazy-imports the Modal SDK — importing it eagerly at module load slows down
uvicorn cold-start by ~500ms.
"""
from __future__ import annotations

import os
from typing import Optional


APP_NAME = os.environ.get("MODAL_APP_NAME", "j-training")


def _lookup(fn_name: str):
    """Fetch a deployed Modal function reference. Requires:
      - MODAL_TOKEN_ID / MODAL_TOKEN_SECRET in env (or ~/.modal.toml)
      - `modal deploy training/train.py` already run against this Modal account
    """
    import modal  # heavy import — deferred
    return modal.Function.from_name(APP_NAME, fn_name)


def dispatch_smoke(run_id: str, webhook_url: str, webhook_secret: str) -> str:
    """Fire the smoke_test function. Returns modal task id.
    Costs ~$0 (CPU-only, 5s). Use to verify plumbing before spending on GPUs."""
    fn = _lookup("smoke_test")
    call = fn.spawn(run_id=run_id, webhook_url=webhook_url,
                    webhook_secret=webhook_secret)
    return call.object_id


def dispatch(run_id: str, base_model: str, training_method: str,
             dataset_url: str, lora_rank: int, learning_rate: float,
             epochs: int, batch_size: int,
             webhook_url: str, webhook_secret: str) -> str:
    """Fire a real training run. Returns modal task id.
    Costs $1-5 depending on model/dataset size."""
    fn = _lookup("train")
    call = fn.spawn(
        run_id=run_id, base_model=base_model, training_method=training_method,
        dataset_url=dataset_url, lora_rank=lora_rank,
        learning_rate=learning_rate, epochs=epochs, batch_size=batch_size,
        webhook_url=webhook_url, webhook_secret=webhook_secret,
    )
    return call.object_id


def cancel(modal_task_id: str) -> bool:
    """Cancel a running task. Idempotent — returns True if cancel attempted."""
    try:
        import modal
        call = modal.FunctionCall.from_id(modal_task_id)
        call.cancel(terminate_containers=True)
        return True
    except Exception:
        return False


def is_configured() -> bool:
    return bool(os.environ.get("MODAL_TOKEN_ID")
                and os.environ.get("MODAL_TOKEN_SECRET"))
