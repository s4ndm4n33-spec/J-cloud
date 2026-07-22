"""SFT + DPO exporters. Mongo → JSONL → storage.

Reads directly from `db` (motor). Never fails silently — every skipped row is
counted separately so the dataset row shows both `row_count` and `skipped`.
"""
from __future__ import annotations

import io
import json
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from .storage import put_bytes


def _jsonl(row: dict) -> bytes:
    return (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


async def export_sft(db: AsyncIOMotorDatabase, dataset_id: str,
                     row_limit: int = 5000,
                     date_from: Optional[str] = None,
                     date_to: Optional[str] = None) -> dict:
    """Chronicle `ai_answer` rows with verdict=passed → SFT JSONL.

    Output shape (chat template):
        {"messages": [{"role":"user","content":...},
                      {"role":"assistant","content":...}],
         "meta": {...}}
    """
    q: dict = {"kind": "ai_answer", "verdict": "passed"}
    if date_from or date_to:
        ts_q: dict = {}
        if date_from: ts_q["$gte"] = date_from
        if date_to:   ts_q["$lte"] = date_to
        q["ts"] = ts_q

    buf = io.BytesIO()
    kept = skipped = 0
    async for doc in db.chronicle_entries.find(q, {"_id": 0}).limit(row_limit):
        prompt = (doc.get("prompt") or "").strip()
        response = (doc.get("response") or "").strip()
        if not prompt or not response:
            skipped += 1
            continue
        buf.write(_jsonl({
            "messages": [
                {"role": "user",      "content": prompt},
                {"role": "assistant", "content": response},
            ],
            "meta": {
                "chronicle_id": doc.get("id"),
                "model": doc.get("model"),
                "provider": doc.get("provider"),
                "scope": doc.get("scope"),
                "ts": doc.get("ts"),
            },
        }))
        kept += 1

    data = buf.getvalue()
    key = f"datasets/{dataset_id}.sft.jsonl"
    url = put_bytes(key, data, content_type="application/x-ndjson")
    return {
        "format": "sft",
        "row_count": kept,
        "skipped": skipped,
        "size_bytes": len(data),
        "download_url": url,
        "s3_key": key,
    }


async def export_dpo(db: AsyncIOMotorDatabase, dataset_id: str,
                     row_limit: int = 5000,
                     only_approved: bool = True) -> dict:
    """knowledge_dpo_candidates → DPO JSONL.

    only_approved=True skips candidates that haven't been triaged in the
    reviewer. Set False for exploratory "everything we ever stashed" exports.

    Output shape (TRL DPOTrainer):
        {"prompt": ..., "chosen": ..., "rejected": ..., "meta": {...}}
    """
    q: dict = {}
    if only_approved:
        q["status"] = "approved"

    buf = io.BytesIO()
    kept = skipped = 0
    async for doc in db.knowledge_dpo_candidates.find(q, {"_id": 0}).limit(row_limit):
        fact = await db.knowledge_facts.find_one(
            {"id": doc.get("chosen_fact_id")},
            {"_id": 0, "title": 1, "body": 1},
        )
        if not fact:
            skipped += 1
            continue
        chosen = f"{fact.get('title','')}\n\n{fact.get('body','')}".strip()
        rejected = (
            f"{doc.get('rejected_title','')}\n\n{doc.get('rejected_body','')}"
        ).strip()
        if not chosen or not rejected:
            skipped += 1
            continue
        buf.write(_jsonl({
            "prompt": doc.get("query", ""),
            "chosen": chosen,
            "rejected": rejected,
            "meta": {
                "dpo_id": doc.get("id"),
                "category": doc.get("category"),
                "reject_reason": doc.get("reject_reason"),
                "ts": doc.get("ts"),
            },
        }))
        kept += 1

    data = buf.getvalue()
    key = f"datasets/{dataset_id}.dpo.jsonl"
    url = put_bytes(key, data, content_type="application/x-ndjson")
    return {
        "format": "dpo",
        "row_count": kept,
        "skipped": skipped,
        "size_bytes": len(data),
        "download_url": url,
        "s3_key": key,
    }
