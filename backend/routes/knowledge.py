"""Knowledge (aka J's Mind) — REST endpoints.

- GET  /api/knowledge/facts?category=&tag=&q=&limit=
- DELETE /api/knowledge/facts/{fact_id}
- GET  /api/knowledge/proposals?status=pending
- POST /api/knowledge/proposals/{prop_id}/{action}       (accept | reject)
- POST /api/knowledge/search                             (Tavily passthrough w/ auto-learn)
- POST /api/knowledge/recall                             (semantic recall for UI debug)
- GET  /api/knowledge/categories
- GET  /api/knowledge/stats
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, TAVILY_API_KEY
from core import knowledge as km

router = APIRouter()


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
