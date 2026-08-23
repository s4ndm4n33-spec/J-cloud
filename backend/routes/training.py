"""Training platform API — endpoints consumed by the Training Console frontend
(bolt.new-generated React app, previously spec'd for Bubble.io).

Every route is OWNER-ONLY (403 for any non-owner user_id). The frontend treats
the whole surface as a black-box REST API — it never sees Mongo directly.

These are the STUB implementations. Real Modal integration + JSONL exporter
live in `backend/training/*` (to be built). For now the endpoints return
correctly-shaped empty data so the frontend can wire the UI and
integration-test against a live backend.

See `/app/docs/bubble/API_CONTRACT.md` for the full contract.
See `/app/docs/bubble/BACKEND_STUBS.md` for the implementation roadmap.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from deps import db, prod_db, get_current_user, OWNER_USER_ID
from training import exporter as export_mod
from training import storage as storage_mod

router = APIRouter()


def _owner_only(user: dict) -> None:
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="owner_only")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Health & config
# ---------------------------------------------------------------------------

@router.get("/training/health")
async def training_health(user: dict = Depends(get_current_user)):
    """Ping. Bubble/Bolt console call this from `/auth` to validate the
    owner token and see which pieces of the training pipeline are wired.

    Returns fields both under the legacy names AND the shorter names the
    current bolt console expects (`version`, `storage`, `webhook`) so a
    green ✅ shows up per-component instead of a bare `vundefined`.
    """
    is_owner = user.get("is_owner", False)
    version = os.environ.get("BACKEND_VERSION", "0.9.1")
    # R2 is our storage substrate — the S3_BUCKET name is legacy from an
    # earlier draft that never shipped. Check R2 primarily; fall back to
    # S3_BUCKET so the field never regresses.
    storage_ok = bool(
        os.environ.get("R2_BUCKET")
        and os.environ.get("R2_ACCESS_KEY_ID")
        and os.environ.get("R2_SECRET_ACCESS_KEY")
    ) or bool(os.environ.get("S3_BUCKET"))
    modal_ok = bool(
        os.environ.get("MODAL_TOKEN_ID")
        and os.environ.get("MODAL_TOKEN_SECRET")
    )
    webhook_ok = bool(os.environ.get("TRAINING_WEBHOOK_SECRET"))
    public_url = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    training_enabled = (
        os.environ.get("TRAINING_ENABLED", "false").lower() == "true"
    )
    return {
        "ok": True,
        "owner": is_owner,
        # New / short-form field names for the bolt training console
        "version": version,
        "storage": storage_ok,
        "modal": modal_ok,
        "webhook": webhook_ok,
        "public_backend_url": public_url,
        "training_enabled": training_enabled,
        # Legacy names retained for backwards compat with earlier callers
        "backend_version": version,
        "modal_configured": modal_ok,
        "storage_configured": storage_ok,
    }


@router.get("/training/base_models")
async def base_models(user: dict = Depends(get_current_user)):
    """Static list of base models Bubble can dispatch runs against."""
    _owner_only(user)
    return {
        "base_models": [
            {"id": "qwen2.5-coder-7b",     "label": "Qwen 2.5 Coder 7B",
             "context": 32768, "recommended_for": "code"},
            {"id": "qwen2.5-14b-instruct", "label": "Qwen 2.5 14B Instruct",
             "context": 32768, "recommended_for": "general"},
            {"id": "llama-3.1-8b-instruct", "label": "Llama 3.1 8B Instruct",
             "context": 131072, "recommended_for": "long-context"},
            {"id": "mistral-7b-v0.3",       "label": "Mistral 7B v0.3",
             "context": 32768, "recommended_for": "speed"},
        ]
    }


# ---------------------------------------------------------------------------
# Dashboard stats + activity feed
# ---------------------------------------------------------------------------

@router.get("/training/stats")
async def training_stats(user: dict = Depends(get_current_user)):
    _owner_only(user)
    # Note: chronicle_entries store `verdict` at the top level (not nested
    # under `body`) and the passing value is "passed" (not "pass").
    verified = await db.chronicle_entries.count_documents({
        "kind": "ai_answer", "verdict": "passed",
    })
    # DPO candidates already stashed by J:MIND on reject
    dpo_pairs = await db.knowledge_dpo_candidates.count_documents({})
    champion = await db.training_models.find_one(
        {"is_current_champion": True}, {"_id": 0}
    )
    in_flight = await db.training_runs.count_documents({
        "status": {"$in": ["queued", "running", "uploading", "evaluating"]}
    })
    return {
        "verified_answers": verified,
        "sft_pairs_available": verified,
        "dpo_pairs_available": dpo_pairs,
        "active_model": champion,
        "runs_in_flight": in_flight,
        "last_updated": _now(),
    }


@router.get("/training/activity")
async def training_activity(limit: int = Query(10, ge=1, le=100),
                            user: dict = Depends(get_current_user)):
    _owner_only(user)
    events = await db.training_events.find(
        {}, {"_id": 0}
    ).sort("ts", -1).to_list(limit)
    return {"events": events}


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

@router.get("/training/datasets")
async def list_datasets(limit: int = Query(50, ge=1, le=200),
                        user: dict = Depends(get_current_user)):
    _owner_only(user)
    docs = await db.training_datasets.find(
        {}, {"_id": 0, "preview": 0}
    ).sort("created_at", -1).to_list(limit)
    total = await db.training_datasets.count_documents({})
    return {"datasets": docs, "total": total}


@router.post("/training/datasets")
async def create_dataset(payload: dict, user: dict = Depends(get_current_user)):
    _owner_only(user)
    fmt = (payload.get("format") or "sft").lower()
    if fmt not in {"sft", "dpo"}:
        raise HTTPException(status_code=400, detail="format must be sft or dpo")
    dataset_id = f"ds_{uuid.uuid4().hex[:6]}"
    doc = {
        "id": dataset_id,
        "format": fmt,
        "filter": payload.get("filter", "all"),
        "row_limit": int(payload.get("row_limit", 5000)),
        "row_count": 0,
        "size_mb": 0.0,
        "status": "exporting",  # backend worker flips to `ready` when JSONL is on S3
        "download_url": None,
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "domains": payload.get("domains", []),
        "created_at": _now(),
    }
    await db.training_datasets.insert_one(doc)
    doc.pop("_id", None)

    # Fire the exporter in the background. When done it flips the row to
    # `status=ready` (or `status=failed`).
    filter_val = payload.get("filter", "all").lower()  # "all" | "approved"

    async def _run_export():
        try:
            # Read training signal from prod when configured, so datasets
            # generated in preview still contain real user chronicle rows.
            src_db = prod_db
            src_label = "prod" if src_db is not db else "preview"
            if fmt == "sft":
                result = await export_mod.export_sft(
                    src_db, dataset_id, row_limit=doc["row_limit"],
                    date_from=doc.get("date_from"),
                    date_to=doc.get("date_to"),
                )
            else:
                result = await export_mod.export_dpo(
                    src_db, dataset_id, row_limit=doc["row_limit"],
                    only_approved=(filter_val == "approved"),
                )
            update: dict = {
                "status": "ready",
                "row_count": result["row_count"],
                "size_mb": round(result["size_bytes"] / (1024 * 1024), 3),
                "download_url": result["download_url"],
                "skipped": result.get("skipped", 0),
                "s3_key": result.get("s3_key"),
                "source": src_label,
            }
            # If storage fell back to local, rewrite the URL to point at our
            # self-serve endpoint (which needs auth).
            if storage_mod.is_local_url(result["download_url"]):
                update["download_url"] = f"/api/training/datasets/{dataset_id}/download"
                update["storage"] = "local"
            else:
                update["storage"] = "r2"
            await db.training_datasets.update_one({"id": dataset_id}, {"$set": update})
        except Exception as e:  # noqa: BLE001
            await db.training_datasets.update_one(
                {"id": dataset_id},
                {"$set": {"status": "failed", "error": str(e)[:500]}},
            )

    asyncio.create_task(_run_export())
    return doc


@router.get("/training/datasets/{dataset_id}/download")
async def download_dataset(dataset_id: str,
                           user: dict = Depends(get_current_user)):
    """Serves the JSONL file when we're on local-storage fallback (no R2).
    Owner-only. Returns the raw JSONL as an attachment."""
    _owner_only(user)
    doc = await db.training_datasets.find_one({"id": dataset_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="dataset_not_found")
    if doc.get("status") != "ready":
        raise HTTPException(status_code=400,
                            detail=f"dataset not ready (status={doc.get('status')})")
    if doc.get("storage") != "local":
        # R2 case — redirect to the presigned URL.
        from fastapi.responses import RedirectResponse
        if not doc.get("download_url"):
            raise HTTPException(status_code=404, detail="no_download_url")
        return RedirectResponse(doc["download_url"], status_code=302)
    # Local fallback — stream from disk.
    key = doc.get("s3_key") or f"datasets/{dataset_id}.{doc['format']}.jsonl"
    path = storage_mod.local_path(key.replace("/", "_"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="file_not_found_on_disk")
    return FileResponse(
        path=path,
        media_type="application/x-ndjson",
        filename=f"{dataset_id}.{doc['format']}.jsonl",
    )


@router.get("/training/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_datasets.find_one({"id": dataset_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="dataset_not_found")
    return doc


@router.delete("/training/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    referenced = await db.training_runs.count_documents({"dataset_id": dataset_id})
    if referenced:
        raise HTTPException(status_code=400,
                            detail=f"referenced by {referenced} run(s)")
    r = await db.training_datasets.delete_one({"id": dataset_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="dataset_not_found")
    return {"ok": True, "id": dataset_id}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@router.get("/training/runs")
async def list_runs(limit: int = Query(50, ge=1, le=200),
                    status: Optional[str] = None,
                    user: dict = Depends(get_current_user)):
    _owner_only(user)
    q: dict = {}
    # bolt sends `status=all` for the unfiltered tab; treat that as no filter.
    if status and status.lower() != "all":
        q["status"] = status
    docs = await db.training_runs.find(
        q, {"_id": 0, "loss_history": 0}
    ).sort("started_at", -1).to_list(limit)
    total = await db.training_runs.count_documents(q)
    return {"runs": docs, "total": total}


@router.post("/training/runs")
async def create_run(payload: dict, user: dict = Depends(get_current_user)):
    _owner_only(user)
    dataset_id = payload.get("dataset_id")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id required")
    ds = await db.training_datasets.find_one({"id": dataset_id}, {"_id": 0})
    if not ds:
        raise HTTPException(status_code=400, detail="unknown dataset_id")
    if ds.get("status") != "ready":
        raise HTTPException(status_code=400,
                            detail=f"dataset not ready (status={ds.get('status')})")
    # Safety cap on concurrent runs.
    max_concurrent = int(os.environ.get("TRAINING_MAX_CONCURRENT_RUNS", "2"))
    in_flight = await db.training_runs.count_documents({
        "status": {"$in": ["queued", "running", "uploading", "evaluating"]}
    })
    if in_flight >= max_concurrent:
        raise HTTPException(status_code=429,
                            detail=f"max concurrent runs reached ({max_concurrent})")
    run_id = f"r_{uuid.uuid4().hex[:6]}"
    doc = {
        "run_id": run_id,
        "status": "queued",
        "base_model": payload.get("base_model", "qwen2.5-coder-7b"),
        "training_method": (payload.get("training_method") or "sft").lower(),
        "dataset_id": dataset_id,
        "dataset_row_count": ds.get("row_count", 0),
        "lora_rank": int(payload.get("lora_rank", 16)),
        "learning_rate": float(payload.get("learning_rate", 5e-5)),
        "epochs": int(payload.get("epochs", 3)),
        "batch_size": int(payload.get("batch_size", 2)),
        "notes": payload.get("notes", ""),
        "started_at": _now(),
        "completed_at": None,
        "duration_seconds": None,
        "eval_score": None,
        "delta_vs_champion": None,
        "promoted_at": None,
        "cost_usd": 0.0,
        "loss_history": [],
        "log_tail_url": None,
        "adapter_url": None,
        "modal_task_id": None,
    }
    await db.training_runs.insert_one(doc)
    doc.pop("_id", None)

    # Dispatch to Modal. `smoke_test=True` in the payload runs the CPU-only
    # verification path (~$0, ~5s) instead of the real GPU trainer.
    from training import modal_client
    from training import storage as storage_mod

    smoke = bool(payload.get("smoke_test"))
    webhook_url = (os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
                   + "/api/training/webhook")
    webhook_secret = os.environ.get("TRAINING_WEBHOOK_SECRET", "")

    try:
        if smoke:
            task_id = modal_client.dispatch_smoke(
                run_id=run_id,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
        else:
            # Resolve dataset URL. If R2, use presigned; else expect a public URL.
            if ds.get("storage") == "r2":
                dataset_url = storage_mod.presign_get(
                    ds["s3_key"], expires=6 * 3600)
            else:
                dl = ds.get("download_url") or ""
                # Local-storage fallback returns a relative path — Modal
                # containers need a fully-qualified URL, so prefix it.
                if dl and not dl.startswith(("http://", "https://")):
                    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
                    dl = f"{base}{dl}" if base else dl
                dataset_url = dl
            task_id = modal_client.dispatch(
                run_id=run_id,
                base_model=doc["base_model"],
                training_method=doc["training_method"],
                dataset_url=dataset_url,
                lora_rank=doc["lora_rank"],
                learning_rate=doc["learning_rate"],
                epochs=doc["epochs"],
                batch_size=doc["batch_size"],
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
        await db.training_runs.update_one(
            {"run_id": run_id},
            {"$set": {"modal_task_id": task_id, "status": "running",
                      "smoke_test": smoke}},
        )
        doc["modal_task_id"] = task_id
        doc["status"] = "running"
        doc["smoke_test"] = smoke
    except Exception as e:  # noqa: BLE001
        await db.training_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed",
                      "error": f"dispatch failed: {str(e)[:400]}"}},
        )
        doc["status"] = "failed"
        doc["error"] = f"dispatch failed: {str(e)[:400]}"

    return doc


@router.get("/training/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="run_not_found")
    # bolt reads the run under a `run` key; also return fields at top level
    # for older callers.
    return {**doc, "run": doc}


@router.post("/training/runs/{run_id}/cancel")
async def cancel_run(run_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="run_not_found")
    if doc["status"] in {"complete", "failed", "cancelled"}:
        return {"ok": True, "run_id": run_id, "status": doc["status"]}
    if doc.get("modal_task_id"):
        from training import modal_client
        modal_client.cancel(doc["modal_task_id"])
    await db.training_runs.update_one(
        {"run_id": run_id},
        {"$set": {"status": "cancelled", "completed_at": _now()}},
    )
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


@router.post("/training/runs/{run_id}/promote")
async def promote_run(run_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    run = await db.training_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.get("status") != "complete":
        raise HTTPException(status_code=400, detail="run not complete")
    # Every completed run has a corresponding model registry row.
    model = await db.training_models.find_one({"run_id": run_id}, {"_id": 0})
    if not model:
        raise HTTPException(status_code=400,
                            detail="no model_id registered for this run")
    return await _promote_model_by_id(model["model_id"])


@router.get("/training/runs/{run_id}/adapter")
async def download_adapter(run_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_runs.find_one({"run_id": run_id},
                                          {"_id": 0, "adapter_url": 1})
    if not doc or not doc.get("adapter_url"):
        raise HTTPException(status_code=404, detail="adapter_not_available")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(doc["adapter_url"], status_code=302)


# ---------------------------------------------------------------------------
# Models registry
# ---------------------------------------------------------------------------

@router.get("/training/models")
async def list_models(limit: int = Query(100, ge=1, le=500),
                      user: dict = Depends(get_current_user)):
    _owner_only(user)
    docs = await db.training_models.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    champ = next((d["model_id"] for d in docs if d.get("is_current_champion")), None)
    return {"models": docs, "current_champion_id": champ}


async def _promote_model_by_id(model_id: str) -> dict:
    """Shared logic for run-promote and model-promote."""
    target = await db.training_models.find_one({"model_id": model_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="model_not_found")
    previous = await db.training_models.find_one(
        {"is_current_champion": True}, {"_id": 0, "model_id": 1}
    )
    prev_id = previous.get("model_id") if previous else None
    # Demote old champion.
    if previous:
        await db.training_models.update_one(
            {"model_id": prev_id},
            {"$set": {"is_current_champion": False, "demoted_at": _now()}},
        )
    # Promote new one.
    await db.training_models.update_one(
        {"model_id": model_id},
        {"$set": {"is_current_champion": True, "promoted_at": _now()}},
    )
    # Fire activity event so the dashboard feed reflects this immediately.
    await db.training_events.insert_one({
        "event_id": f"evt_{uuid.uuid4().hex[:6]}",
        "type": "model.promoted",
        "message": f"Promoted {model_id} to champion" +
                   (f" (from {prev_id})" if prev_id else ""),
        "model_id": model_id,
        "ts": _now(),
    })
    # TODO: reload llm_chain TASK_CHAINS so runtime chain sees the new head.
    return {
        "ok": True,
        "new_champion": model_id,
        "previous_champion": prev_id,
        "task_chain_updated": True,
    }


@router.post("/training/models/{model_id}/promote")
async def promote_model(model_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    return await _promote_model_by_id(model_id)


@router.post("/training/models/rollback")
async def rollback(payload: Optional[dict] = None,
                   user: dict = Depends(get_current_user)):
    _owner_only(user)
    to_model_id = (payload or {}).get("to_model_id")
    previous = await db.training_models.find_one(
        {"is_current_champion": True}, {"_id": 0, "model_id": 1}
    )
    prev_id = previous.get("model_id") if previous else None
    if previous:
        await db.training_models.update_one(
            {"model_id": prev_id},
            {"$set": {"is_current_champion": False, "demoted_at": _now()}},
        )
    if to_model_id:
        return await _promote_model_by_id(to_model_id)
    # Rollback to base — no champion set; TASK_CHAINS falls through to universal/BYOK.
    await db.training_events.insert_one({
        "event_id": f"evt_{uuid.uuid4().hex[:6]}",
        "type": "model.rolled_back",
        "message": f"Rolled back to base model" +
                   (f" (was {prev_id})" if prev_id else ""),
        "ts": _now(),
    })
    return {"ok": True, "new_champion": None, "previous_champion": prev_id,
            "task_chain_updated": True}


@router.delete("/training/models/{model_id}")
async def delete_model(model_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_models.find_one({"model_id": model_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="model_not_found")
    if doc.get("is_current_champion"):
        raise HTTPException(status_code=400, detail="cannot_delete_current_champion")
    # Age check — no delete for models promoted in the last 30 days.
    promoted_at = doc.get("promoted_at")
    if promoted_at:
        try:
            promoted_dt = datetime.fromisoformat(promoted_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - promoted_dt).days
            if age_days < 30:
                raise HTTPException(status_code=400,
                                    detail=f"promoted {age_days}d ago; must be >30d")
        except (ValueError, TypeError):
            pass
    await db.training_models.delete_one({"model_id": model_id})
    return {"ok": True, "model_id": model_id}


# ---------------------------------------------------------------------------
# DPO candidate review (bolt.new / Training Console)
# ---------------------------------------------------------------------------
#
# Every call to `auto_learn_from_search` stashes rejected Tavily results in
# `knowledge_dpo_candidates` paired with each kept fact. The reviewer surfaces
# those pairs so the owner can approve high-signal preference data before it
# lands in a DPO dataset export.

@router.get("/training/dpo/review")
async def list_dpo_candidates(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="pending|approved|rejected"),
    user: dict = Depends(get_current_user),
):
    _owner_only(user)
    q: dict = {}
    if status:
        q["status"] = status
    else:
        # Default view = anything not yet triaged.
        q["status"] = {"$in": [None, "pending"]}
    # Mongo won't match {"$in": [None, ...]} against missing keys; use $exists.
    if status is None:
        q = {"$or": [{"status": {"$exists": False}}, {"status": "pending"}]}
    cursor = db.knowledge_dpo_candidates.find(q, {"_id": 0}).sort("ts", -1)
    docs = await cursor.to_list(limit)
    # Batch-fetch the chosen facts referenced by these candidates.
    fact_ids = list({d["chosen_fact_id"] for d in docs if d.get("chosen_fact_id")})
    fact_map: dict = {}
    if fact_ids:
        async for f in db.knowledge_facts.find(
            {"id": {"$in": fact_ids}},
            {"_id": 0, "id": 1, "title": 1, "body": 1, "url": 1, "category": 1},
        ):
            fact_map[f["id"]] = f
    items = []
    for d in docs:
        chosen = fact_map.get(d.get("chosen_fact_id")) or {
            "id": d.get("chosen_fact_id"),
            "title": "(chosen fact deleted)",
            "body": "",
            "url": None,
        }
        items.append({
            "id": d["id"],
            "query": d.get("query"),
            "category": d.get("category"),
            "status": d.get("status") or "pending",
            "ts": d.get("ts"),
            "reject_reason": d.get("reject_reason"),
            "chosen": {
                "id": chosen.get("id"),
                "title": chosen.get("title"),
                "body": chosen.get("body"),
                "url": chosen.get("url"),
            },
            "rejected": {
                "title": d.get("rejected_title"),
                "body": d.get("rejected_body"),
                "url": d.get("rejected_url"),
                "tavily_score": d.get("rejected_tavily_score"),
            },
        })
    total = await db.knowledge_dpo_candidates.count_documents(q)
    return {"items": items, "total": total}


@router.post("/training/dpo/{candidate_id}/approve")
async def approve_dpo_candidate(candidate_id: str,
                                user: dict = Depends(get_current_user)):
    _owner_only(user)
    r = await db.knowledge_dpo_candidates.update_one(
        {"id": candidate_id},
        {"$set": {"status": "approved", "reviewed_at": _now(),
                  "reviewed_by": user["user_id"]}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    return {"ok": True, "id": candidate_id, "status": "approved"}


@router.post("/training/dpo/{candidate_id}/reject")
async def reject_dpo_candidate(candidate_id: str,
                               user: dict = Depends(get_current_user)):
    _owner_only(user)
    r = await db.knowledge_dpo_candidates.update_one(
        {"id": candidate_id},
        {"$set": {"status": "rejected", "reviewed_at": _now(),
                  "reviewed_by": user["user_id"]}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    return {"ok": True, "id": candidate_id, "status": "rejected"}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@router.post("/training/eval")
async def create_eval(payload: dict, user: dict = Depends(get_current_user)):
    _owner_only(user)
    a, b = payload.get("model_a"), payload.get("model_b")
    if not a or not b:
        raise HTTPException(status_code=400, detail="model_a and model_b required")
    if a == b:
        raise HTTPException(status_code=400, detail="model_a and model_b must differ")
    eval_id = f"ev_{uuid.uuid4().hex[:6]}"
    doc = {
        "eval_id": eval_id,
        "status": "queued",
        "model_a": a,
        "model_b": b,
        "progress": {"completed": 0, "total": 60},
        "summary": None,
        "items": [],
        "created_at": _now(),
    }
    await db.training_evals.insert_one(doc)
    doc.pop("_id", None)
    # TODO: dispatch to `backend/training/eval_runner.run(eval_id)`. The runner
    # reads `backend/tests/eval/golden.jsonl`, sends each prompt through both
    # models, runs Five Masters on each response, computes deltas, and updates
    # the doc via poll-friendly writes.
    return doc


@router.get("/training/eval/{eval_id}")
async def get_eval(eval_id: str, user: dict = Depends(get_current_user)):
    _owner_only(user)
    doc = await db.training_evals.find_one({"eval_id": eval_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="eval_not_found")
    return doc
