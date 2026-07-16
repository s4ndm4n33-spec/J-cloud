"""Knowledge (aka J's Mind) — REST endpoints.

- GET  /api/knowledge/facts?category=&tag=&q=&limit=
- DELETE /api/knowledge/facts/{fact_id}
- GET  /api/knowledge/proposals?status=pending
- POST /api/knowledge/proposals/{prop_id}/{action}       (accept | reject)
- POST /api/knowledge/search                             (Tavily passthrough w/ auto-learn)
- POST /api/knowledge/recall                             (semantic recall for UI debug)
- GET  /api/knowledge/categories
- GET  /api/knowledge/stats
- GET  /api/knowledge/export?format=openai_sft           (streams JSONL, one row per fact)
- GET  /api/training/dpo?format=dpo                      (streams JSONL of chronicle ai_answer pairs)
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from deps import db, get_current_user, TAVILY_API_KEY
from core import knowledge as km

router = APIRouter()


def _read_agents_md() -> str:
    """Load AGENTS.md as the SFT system prompt; fall back to a stub if missing."""
    p = Path("/app/AGENTS.md")
    if p.exists():
        return p.read_text()
    return "You are J. Sardonic, capable, kind. Full Five Masters gauntlet on all code."


# Ensure indexes on first request per process (idempotent — cheap).
# We do this lazily instead of via on_event('startup') because that hook is
# deprecated in modern FastAPI.
_indexed = False


async def _ensure_ready():
    global _indexed
    if not _indexed:
        try:
            await km._ensure_indexes(db)
            _indexed = True
        except Exception:  # noqa: BLE001
            pass


@router.get("/knowledge/categories")
async def knowledge_categories(_user: dict = Depends(get_current_user)):
    await _ensure_ready()
    return {"categories": km.CATEGORIES}


@router.get("/knowledge/stats")
async def knowledge_stats(_user: dict = Depends(get_current_user)):
    await _ensure_ready()
    total = await db.knowledge_facts.count_documents({})
    pending = await db.knowledge_proposals.count_documents({"status": "pending"})
    accepted = await db.knowledge_proposals.count_documents({"status": "accepted"})
    rejected = await db.knowledge_proposals.count_documents({"status": "rejected"})
    per_cat_cursor = db.knowledge_facts.aggregate([
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ])
    per_cat = [{"category": d["_id"], "count": d["count"]} async for d in per_cat_cursor]
    return {
        "total_facts": total,
        "proposals": {"pending": pending, "accepted": accepted, "rejected": rejected},
        "per_category": per_cat,
    }


@router.get("/knowledge/facts")
async def knowledge_facts(
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 50,
    _user: dict = Depends(get_current_user),
):
    await _ensure_ready()
    docs = await km.list_facts(db, category=category, tag=tag, q=q, limit=limit)
    return {"facts": docs, "count": len(docs)}


@router.delete("/knowledge/facts/{fact_id}")
async def knowledge_delete_fact(fact_id: str, _user: dict = Depends(get_current_user)):
    r = await km.delete_fact(db, fact_id)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail="fact not found")
    return r


@router.get("/knowledge/proposals")
async def knowledge_proposals(
    status: str = "pending", limit: int = 100,
    _user: dict = Depends(get_current_user),
):
    docs = await km.list_proposals(db, status=status, limit=limit)
    return {"proposals": docs, "count": len(docs)}


@router.post("/knowledge/proposals/{prop_id}/{action}")
async def knowledge_resolve_proposal(
    prop_id: str, action: str, payload: dict | None = None,
    _user: dict = Depends(get_current_user),
):
    if action not in {"accept", "reject"}:
        raise HTTPException(status_code=400, detail="action must be accept or reject")
    r = await km.resolve_proposal(db, prop_id, action, edits=(payload or {}).get("edits"))
    if r.get("error"):
        raise HTTPException(status_code=404, detail=r["error"])
    return r


@router.post("/knowledge/search")
async def knowledge_search(payload: dict, _user: dict = Depends(get_current_user)):
    """Convenience passthrough — Tavily search + auto-learn (no LLM extract)."""
    await _ensure_ready()
    query = (payload or {}).get("query", "")
    max_results = int((payload or {}).get("max_results", 5))
    result = await km.web_search(db, TAVILY_API_KEY, query, max_results=max_results)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    if (payload or {}).get("learn", True):
        result["_learn"] = await km.auto_learn_from_search(db, result)
    return result


@router.post("/knowledge/recall")
async def knowledge_recall(payload: dict, _user: dict = Depends(get_current_user)):
    await _ensure_ready()
    query = (payload or {}).get("query", "")
    k = int((payload or {}).get("k", 5))
    category = (payload or {}).get("category")
    hits = await km.recall(db, query, k=k, category=category)
    return {"query": query, "hits": hits, "count": len(hits)}



# ---------- Training-data exports -----------------------------------------
#
# These endpoints turn J's runtime substrate into a proper training corpus.
# Two shapes:
#
#   openai_sft  — one JSONL row per J:MIND fact, in OpenAI fine-tune format
#                 {"messages":[{system: AGENTS.md}, {user: "..."}, {assistant: "..."}]}
#
#   dpo         — one JSONL row per chronicle ai_answer (preferred pattern for
#                 preference learning; we emit chosen=response, rejected=null
#                 today, but the schema is DPO-ready for when we start capturing
#                 pre-CIG drafts too).
#
# Both stream to keep memory flat.

@router.get("/knowledge/export")
async def knowledge_export(
    format: str = "openai_sft",
    category: str | None = None,
    _user: dict = Depends(get_current_user),
):
    """Stream J:MIND facts as JSONL training data."""
    if format not in {"openai_sft", "raw"}:
        raise HTTPException(status_code=400, detail=f"unknown format: {format}")
    await _ensure_ready()
    system_prompt = _read_agents_md() if format == "openai_sft" else ""

    query: dict = {}
    if category:
        query["category"] = category

    async def gen():
        async for doc in db.knowledge_facts.find(query, {"_id": 0, "embedding": 0}):
            if format == "openai_sft":
                # Build a (user, assistant) pair from the fact. The "user" side
                # reconstructs a plausible query that would surface this fact;
                # `source_query` is the actual prior search that captured it.
                user_msg = doc.get("source_query") or f"Tell me about: {doc.get('title', '')}"
                assistant_msg = f"{doc.get('title', '')}\n\n{doc.get('body', '')}"
                src = doc.get("source_url", "")
                if src:
                    assistant_msg += f"\n\nSource: {src}"
                row = {"messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": assistant_msg},
                ], "metadata": {
                    "id": doc.get("id"), "category": doc.get("category"),
                    "tags": doc.get("tags", []), "source_url": src,
                }}
            else:  # raw
                row = doc
            yield json.dumps(row, ensure_ascii=False) + "\n"

    return StreamingResponse(
        gen(), media_type="application/x-ndjson",
        headers={"Content-Disposition":
                 f'attachment; filename="j_mind_{format}.jsonl"'},
    )


@router.get("/training/dpo")
async def training_dpo_export(
    scope: str | None = None,   # "chat" | "agent" | None (both)
    since: str | None = None,   # ISO date string; only entries after this ts
    _user: dict = Depends(get_current_user),
):
    """Stream chronicle ai_answer rows as DPO-shaped JSONL.

    Emits: {"prompt": <user_msg>, "chosen": <J response>, "rejected": null,
             "meta": {model, provider, verdict, scope, ts}}

    Today `rejected` is always null. When we start capturing pre-CIG raw drafts,
    that field will hold them; the schema is already right so no consumer
    change is needed downstream.
    """
    query: dict = {"kind": "ai_answer"}
    if scope:
        query["scope"] = scope
    if since:
        query["ts"] = {"$gte": since}

    async def gen():
        async for doc in db.chronicle_entries.find(query, {"_id": 0}):
            if not doc.get("prompt") or not doc.get("response"):
                continue
            if doc.get("verdict") == "offline":
                continue  # never train on offline stubs
            row = {
                "prompt": doc["prompt"],
                "chosen": doc["response"],
                "rejected": doc.get("rejected_response"),  # placeholder
                "meta": {
                    "id": doc.get("id"),
                    "model": doc.get("model"),
                    "provider": doc.get("provider"),
                    "verdict": doc.get("verdict"),
                    "scope": doc.get("scope"),
                    "steps_taken": doc.get("steps_taken"),
                    "tool_names": doc.get("tool_names", []),
                    "ts": doc.get("ts"),
                },
            }
            yield json.dumps(row, ensure_ascii=False) + "\n"

    return StreamingResponse(
        gen(), media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="j_dpo.jsonl"'},
    )
