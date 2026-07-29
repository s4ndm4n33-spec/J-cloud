"""Modal → backend webhook receiver.

Mounted at `POST /api/training/webhook`. HMAC-signed via
`TRAINING_WEBHOOK_SECRET`. Updates the `training_runs` row and pushes an
event onto `training_events` (activity feed) on terminal state changes.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request

from deps import db

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/training/webhook")
async def modal_webhook(request: Request):
    secret = os.environ.get("TRAINING_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="webhook_disabled")

    body = await request.body()
    sig = request.headers.get("X-Modal-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="bad_signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad json")

    run_id = payload.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")

    status = payload.get("status")
    set_ops: dict = {}
    push_ops: dict = {}

    if status == "running":
        set_ops["status"] = "running"
        if payload.get("loss") is not None:
            push_ops["loss_history"] = {
                "step":  payload.get("step"),
                "loss":  payload.get("loss"),
                "epoch": payload.get("epoch"),
                "ts":    _now(),
            }
        if payload.get("message"):
            push_ops["log_lines"] = {
                "ts": _now(), "msg": payload["message"],
            }
    elif status == "complete":
        set_ops.update({
            "status": "complete",
            "completed_at": _now(),
            "adapter_url": payload.get("adapter_url"),
            "final_loss": payload.get("final_loss"),
            "smoke_test": bool(payload.get("smoke_test")),
        })
    elif status == "failed":
        set_ops.update({
            "status": "failed",
            "completed_at": _now(),
            "error": (payload.get("error") or "")[:500],
        })

    ops: dict = {}
    if set_ops:  ops["$set"] = set_ops
    if push_ops: ops["$push"] = push_ops
    if not ops:
        return {"ok": True, "no_op": True}

    await db.training_runs.update_one({"run_id": run_id}, ops)

    # On a real (non-smoke) successful completion, mint a training_models row
    # so the adapter shows up in bolt's Models page and can be promoted.
    if (status == "complete"
            and payload.get("adapter_url")
            and not payload.get("smoke_test")):
        run_doc = await db.training_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run_doc:
            model_id = f"m_{run_id.split('_', 1)[-1]}"
            base_short = (run_doc.get("base_model") or "unknown").split("-")[0]
            existing = await db.training_models.count_documents(
                {"base_model": run_doc.get("base_model")})
            display_name = f"j-{base_short}-lora-v{existing + 1}"
            await db.training_models.update_one(
                {"model_id": model_id},
                {"$setOnInsert": {
                    "model_id": model_id,
                    "name": display_name,
                    "run_id": run_id,
                    "base_model": run_doc.get("base_model"),
                    "training_method": run_doc.get("training_method"),
                    "adapter_url": payload.get("adapter_url"),
                    "final_loss": payload.get("final_loss"),
                    "dataset_id": run_doc.get("dataset_id"),
                    "lora_rank": run_doc.get("lora_rank"),
                    "epochs": run_doc.get("epochs"),
                    "is_current_champion": False,
                    "eval_score": None,
                    "created_at": _now(),
                }},
                upsert=True,
            )

    if status in ("complete", "failed"):
        await db.training_events.insert_one({
            "event_id": f"evt_{run_id}_{status}",
            "type": f"run.{status}",
            "message": (f"Run {run_id} {status}"
                        + (f": {payload.get('error')}"
                           if status == "failed" else "")),
            "run_id": run_id,
            "ts": _now(),
        })

    return {"ok": True}
