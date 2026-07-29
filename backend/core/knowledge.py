"""J's Mind — a per-user persistent knowledge store with semantic recall.

Two tiers, one goal:

    Tier 1 — `knowledge_facts` (MongoDB, keyword+tag searchable, embedded).
             The durable memory. Every fact carries a `user_id` and a
             `shared` flag: non-owner users see their own facts UNION the
             owner-curated `shared=True` baseline. Owner sees everything.
    Tier 2 — `knowledge_proposals` (MongoDB, pending-approval queue).
             Insights J *thinks* are worth remembering but haven't been
             confirmed by a human yet. Also `user_id`-scoped.

Auto-learn: after every `web_search`, J summarises the top hits into a
handful of durable facts (via LLM). These are stored scoped to the caller;
owner-triggered searches can promote learned facts to the shared baseline
by passing `shared=True`. Non-owner learning is always private.

Opt-in: `propose_learning(insight)` creates a proposal instead of writing
straight to the fact table. The user gets a MIND panel to ACCEPT / EDIT /
REJECT.

Retrieval: `recall(query, user_id=..., is_owner=..., k=...)` uses fastembed
cosine similarity for semantic recall, falling back to Mongo text search
when embeddings aren't available. Injected into the agent's system context
per turn so J's answers get sharper as *the caller's own* store grows.

Scope: per-user (fixed 2026-02 — was global, which leaked context across
users once the app went multi-tenant).
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import numpy as np

# fastembed is heavy on first-import (~150MB ONNX cache). We lazy-load it in
# a background task so the first API call doesn't stall for 30 seconds.
_EMBEDDER = None
_EMBEDDER_LOCK = asyncio.Lock()
_EMBED_DIM = 384  # BAAI/bge-small-en-v1.5 output dim


async def _get_embedder():
    """Lazy singleton loader for the embedding model. Idempotent."""
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    async with _EMBEDDER_LOCK:
        if _EMBEDDER is not None:
            return _EMBEDDER
        from fastembed import TextEmbedding
        # Run the blocking model-download in a thread so we don't block loop.
        _EMBEDDER = await asyncio.to_thread(
            TextEmbedding, model_name="BAAI/bge-small-en-v1.5",
        )
    return _EMBEDDER


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed one or many strings. Returns list of L2-normalised float vectors."""
    if not texts:
        return []
    model = await _get_embedder()
    vectors = await asyncio.to_thread(lambda: list(model.embed(texts)))
    out: list[list[float]] = []
    for v in vectors:
        arr = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(arr))
        if n > 0:
            arr = arr / n
        out.append(arr.tolist())
    return out


# ---------- Categories (help J route "mechanical" queries to real domains) ----

CATEGORIES = [
    "automotive",       # cars, motorcycles, service manuals, torque specs
    "hvac",             # heating / cooling / refrigeration
    "plumbing",
    "electrical",       # wiring, breakers, code
    "appliances",       # fridges, dishwashers, washers
    "engineering",      # general mech-e / civil / materials
    "electronics",      # PCB, embedded, IoT hardware
    "software",         # the traditional coding lane
    "devops",           # infra, cloud, deploys
    "web-dev",
    "data-science",
    "physics",
    "math",
    "chemistry",
    "biology",
    "general",          # everything else
]


def guess_category(text: str) -> str:
    """Cheap keyword heuristic — LLM can override via `category` arg."""
    t = text.lower()
    hints = [
        (("torque", "nissan", "toyota", "ford", "honda", "chevrolet", "cylinder",
          "engine", "brake", "transmission", "spark plug", "obd", "vin", "door lock",
          "differential", "carburet", "alternator"), "automotive"),
        (("hvac", "refrigerant", "compressor", "thermostat", "duct", "furnace",
          "condenser", "evaporator", "r-410a", "r410a", "btu"), "hvac"),
        (("plumbing", "pex", "pvc", "sewer", "drain", "faucet", "toilet flapper",
          "water heater"), "plumbing"),
        (("voltage", "amperage", "gfci", "breaker", "romex", "wire gauge",
          "3-phase", "neutral", "ground fault"), "electrical"),
        (("fridge", "refrigerator", "dishwasher", "washing machine", "dryer",
          "oven", "microwave"), "appliances"),
        (("react", "typescript", "python", "fastapi", "django", "node", "npm",
          "yarn", "next.js", "vue", "webpack", "vite"), "web-dev"),
        (("kubernetes", "docker", "aws", "gcp", "azure", "terraform", "ci/cd"), "devops"),
        (("neural network", "gradient descent", "tensor", "pytorch", "sklearn",
          "dataframe", "pandas"), "data-science"),
        (("newton", "torque", "moment of inertia", "stress-strain", "yield",
          "modulus", "friction coefficient"), "engineering"),
        (("resistor", "capacitor", "microcontroller", "arduino", "raspberry pi",
          "gpio", "i2c", "spi"), "electronics"),
    ]
    for keywords, cat in hints:
        if any(k in t for k in keywords):
            return cat
    return "general"


# ---------- CRUD on the fact table --------------------------------------------


async def _ensure_indexes(db) -> None:
    """Idempotent — cheap to re-run per module load."""
    await db.knowledge_facts.create_index([("id", 1)], unique=True)
    await db.knowledge_facts.create_index([("category", 1)])
    await db.knowledge_facts.create_index([("tags", 1)])
    await db.knowledge_facts.create_index([("source_url", 1)])
    await db.knowledge_facts.create_index([("ts", -1)])
    await db.knowledge_facts.create_index([("title", "text"), ("body", "text")])
    # Per-user scoping (added 2026-02) — every fact is owned by exactly one
    # user; `shared=True` promotes it to J's public baseline visible to all.
    # Compound index makes the recall filter (user_id OR shared) O(log n).
    await db.knowledge_facts.create_index([("user_id", 1)])
    await db.knowledge_facts.create_index([("shared", 1)])
    await db.knowledge_facts.create_index([("user_id", 1), ("category", 1)])
    await db.knowledge_proposals.create_index([("id", 1)], unique=True)
    await db.knowledge_proposals.create_index([("status", 1), ("ts", -1)])
    await db.knowledge_proposals.create_index([("user_id", 1), ("status", 1)])
    await db.knowledge_search_log.create_index([("ts", -1)])
    await db.knowledge_search_log.create_index([("user_id", 1)])
    # DPO candidates: rejected Tavily results kept for preference-pair training.
    await db.knowledge_dpo_candidates.create_index([("ts", -1)])
    await db.knowledge_dpo_candidates.create_index([("chosen_fact_id", 1)])
    await db.knowledge_dpo_candidates.create_index([("user_id", 1)])


async def migrate_legacy_facts(db, owner_user_id: str) -> dict[str, int]:
    """One-shot idempotent migration for facts predating per-user scoping.
    All rows without `user_id` are marked as owner-owned + shared — this
    treats the legacy pool as J's public baseline. Safe to re-run.
    """
    if not owner_user_id:
        return {"migrated": 0, "reason": "no OWNER_USER_ID configured"}
    r = await db.knowledge_facts.update_many(
        {"user_id": {"$exists": False}},
        {"$set": {"user_id": owner_user_id, "shared": True}},
    )
    # Same for proposals — legacy proposals become owner-owned.
    p = await db.knowledge_proposals.update_many(
        {"user_id": {"$in": [None, ""]}},
        {"$set": {"user_id": owner_user_id}},
    )
    return {"migrated_facts": r.modified_count,
            "migrated_proposals": p.modified_count}


def _scope_filter(user_id: str, is_owner: bool) -> dict[str, Any]:
    """Return the Mongo query fragment that scopes reads to a caller.

    - Owner sees everything (empty filter).
    - Non-owner sees their own facts OR facts explicitly marked `shared=True`.
    """
    if is_owner:
        return {}
    return {"$or": [{"user_id": user_id}, {"shared": True}]}


# ---------- Freshness / time-decay -----------------------------------------
#
# In engineering / mechanical / automotive knowledge, staleness is a safety
# issue — a 2004 torque spec vs a 2025 recall notice deserve different
# weight in retrieval. We store an ISO ts on every fact and derive a
# freshness multiplier at recall time.  Fresh (< 30 days) → 1.0.
# Older facts decay LINEARLY to 0.3 over 180 days, then floor there — we
# never actively delete based on age; we just quiet stale rows in ranking.
# `ref_count` bumps reset ts_last_seen, so a fact that keeps getting
# re-discovered stays fresh naturally.

FRESHNESS_FLOOR = 0.3
FRESHNESS_FULL_DAYS = 30
FRESHNESS_DECAY_DAYS = 180


def _freshness_score(ts_last_seen_iso: str) -> float:
    """Return 1.0 for fresh facts, decaying linearly to FRESHNESS_FLOOR over ~180d."""
    if not ts_last_seen_iso:
        return FRESHNESS_FLOOR
    try:
        ts = datetime.fromisoformat(ts_last_seen_iso.replace("Z", "+00:00"))
    except Exception:
        return FRESHNESS_FLOOR
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    if age_days <= FRESHNESS_FULL_DAYS:
        return 1.0
    if age_days >= FRESHNESS_DECAY_DAYS:
        return FRESHNESS_FLOOR
    # Linear decay between 30d (1.0) and 180d (FLOOR).
    span = FRESHNESS_DECAY_DAYS - FRESHNESS_FULL_DAYS
    frac = (age_days - FRESHNESS_FULL_DAYS) / span
    return 1.0 - (1.0 - FRESHNESS_FLOOR) * frac


async def add_fact(
    db,
    *,
    user_id: str,
    title: str,
    body: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    source_url: str = "",
    source_query: str = "",
    signer: str = "J",
    shared: bool = False,
    embed_now: bool = True,
) -> dict[str, Any]:
    """Insert or upsert a fact scoped to `user_id`. `shared=True` promotes it
    to J's public baseline (visible to all users). De-dup key is
    (user_id, source_url, title) — same URL from two users = two rows, so
    contexts stay separated.
    """
    if not user_id:
        return {"error": "user_id required"}
    title = (title or "").strip()[:200]
    body = (body or "").strip()[:6000]
    if not title or not body:
        return {"error": "title and body required"}
    category = (category or "general").strip().lower() or "general"
    tags_clean = [str(t).lower().strip()[:32] for t in (tags or []) if str(t).strip()][:8]

    # De-dup: same user + URL + title = bump ref_count instead of inserting.
    if source_url:
        prior = await db.knowledge_facts.find_one(
            {"user_id": user_id, "source_url": source_url, "title": title},
            {"_id": 0},
        )
        if prior:
            await db.knowledge_facts.update_one(
                {"id": prior["id"]},
                {"$inc": {"ref_count": 1},
                 "$set": {"ts_last_seen": datetime.now(timezone.utc).isoformat()}},
            )
            return {"ok": True, "id": prior["id"], "deduped": True}

    fact_id = f"fact_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": fact_id,
        "user_id": user_id,
        "shared": bool(shared),
        "title": title,
        "body": body,
        "category": category,
        "tags": tags_clean,
        "source_url": source_url,
        "source_query": source_query[:400],
        "signer": signer,
        "ref_count": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "ts_last_seen": datetime.now(timezone.utc).isoformat(),
        "embedding": None,
    }
    if embed_now:
        try:
            [vec] = await embed([f"{title}. {body}"])
            doc["embedding"] = vec
        except Exception:
            doc["embedding"] = None  # graceful degrade to keyword-only
    await db.knowledge_facts.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "id": fact_id, "deduped": False}


async def list_facts(
    db,
    *,
    user_id: str,
    is_owner: bool = False,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = dict(_scope_filter(user_id, is_owner))
    if category:
        query["category"] = category
    if tag:
        query["tags"] = tag
    if q:
        query["$text"] = {"$search": q}
    docs = await db.knowledge_facts.find(query, {"_id": 0, "embedding": 0}) \
        .sort("ts", -1).to_list(int(limit))
    return docs


async def delete_fact(
    db, fact_id: str, *, user_id: str, is_owner: bool = False,
) -> dict[str, Any]:
    """Delete a fact. Non-owners can only delete their OWN facts (not shared
    baseline ones from the owner). Owner can delete anything.
    """
    if is_owner:
        r = await db.knowledge_facts.delete_one({"id": fact_id})
    else:
        r = await db.knowledge_facts.delete_one(
            {"id": fact_id, "user_id": user_id},
        )
    return {"ok": r.deleted_count == 1}


async def share_fact(
    db, fact_id: str, *, is_owner: bool, shared: bool = True,
) -> dict[str, Any]:
    """Owner-only: promote/demote a fact's `shared` flag. Non-owners cannot
    make their own facts visible to other users.
    """
    if not is_owner:
        return {"error": "only the owner can share facts"}
    r = await db.knowledge_facts.update_one(
        {"id": fact_id}, {"$set": {"shared": bool(shared)}},
    )
    if r.matched_count == 0:
        return {"error": "fact not found"}
    return {"ok": True, "id": fact_id, "shared": bool(shared)}


# ---------- Semantic recall ---------------------------------------------------


async def recall(
    db,
    query: str,
    *,
    user_id: str,
    is_owner: bool = False,
    k: int = 5,
    category: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return top-K facts most relevant to `query`, scoped to caller.

    Non-owner recall = the user's own facts UNION shared baseline facts.
    Owner recall = everything (per the owner-lock convention).

    Path A (embeddings available): cosine similarity over stored vectors.
    Path B (fallback): Mongo `$text` search — no embeddings needed.
    """
    q = (query or "").strip()
    if not q:
        return []
    base_filter: dict[str, Any] = {"embedding": {"$ne": None}}
    scope = _scope_filter(user_id, is_owner)
    if scope:
        base_filter.update(scope)
    if category:
        base_filter["category"] = category

    # Path A — embedding cosine, blended with freshness.
    try:
        [qvec] = await embed([q])
        # Pull up to 500 candidates (cheap because we don't return the payload
        # yet), score in Python, return top-K.
        candidates = await db.knowledge_facts.find(
            base_filter, {"_id": 0, "id": 1, "title": 1, "body": 1,
                          "category": 1, "tags": 1, "source_url": 1,
                          "embedding": 1, "ref_count": 1,
                          "ts_last_seen": 1, "ts": 1},
        ).to_list(500)
        if candidates:
            qv = np.asarray(qvec, dtype=np.float32)
            scored: list[tuple[float, float, dict]] = []
            for c in candidates:
                emb = c.pop("embedding", None)
                if not emb:
                    continue
                vv = np.asarray(emb, dtype=np.float32)
                cosine = float(np.dot(qv, vv))
                # Blend cosine with freshness. Fresh facts unchanged; stale
                # facts quieted by up to 30% at the floor. Never zeroed out —
                # a highly-relevant old fact still surfaces if nothing fresher
                # exists.
                fresh = _freshness_score(c.get("ts_last_seen") or c.get("ts", ""))
                blended = cosine * (0.7 + 0.3 * fresh)
                scored.append((blended, cosine, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {**c, "score": round(cos, 4), "blended_score": round(bl, 4)}
                for bl, cos, c in scored[:k] if bl > 0.15
            ]
    except Exception:
        pass  # fall through to text search

    # Path B — text search fallback (works even without an embedder loaded).
    text_query: dict[str, Any] = {"$text": {"$search": q}}
    scope_b = _scope_filter(user_id, is_owner)
    if scope_b:
        text_query.update(scope_b)
    if category:
        text_query["category"] = category
    docs = await db.knowledge_facts.find(
        text_query, {"_id": 0, "score": {"$meta": "textScore"}, "id": 1,
                     "title": 1, "body": 1, "category": 1, "tags": 1,
                     "source_url": 1, "ref_count": 1},
    ).sort([("score", {"$meta": "textScore"})]).to_list(int(k))
    return docs


# ---------- Proposals (opt-in learn-from-conversation) ------------------------


async def add_proposal(
    db,
    *,
    title: str,
    body: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    source: str = "",
    conversation_id: str = "",
    user_id: str = "",
    propose_shared: bool = False,
) -> dict[str, Any]:
    prop_id = f"prop_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": prop_id,
        "title": title[:200],
        "body": body[:6000],
        "category": (category or "general").lower(),
        "tags": [str(t).lower().strip()[:32] for t in (tags or []) if str(t).strip()][:8],
        "source": source[:200],
        "conversation_id": conversation_id,
        "user_id": user_id,
        # `propose_shared` = the user (or J on their behalf) is asking for
        # this to enter J's public baseline. Owner reviews in a dedicated
        # inbox; on accept, the fact is written with shared=True.
        "propose_shared": bool(propose_shared),
        "status": "pending",  # pending | accepted | rejected
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.knowledge_proposals.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_proposals(
    db, *, user_id: str, is_owner: bool = False,
    status: str = "pending", limit: int = 100,
) -> list[dict[str, Any]]:
    q: dict[str, Any] = {"status": status}
    if not is_owner:
        q["user_id"] = user_id
    docs = await db.knowledge_proposals.find(q, {"_id": 0}) \
        .sort("ts", -1).to_list(int(limit))
    return docs


async def resolve_proposal(
    db, prop_id: str, action: str,
    *,
    caller_user_id: str,
    is_owner: bool = False,
    edits: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    prop = await db.knowledge_proposals.find_one({"id": prop_id}, {"_id": 0})
    if not prop:
        return {"error": "not found"}
    # Ownership check — non-owners can only resolve their own proposals.
    if not is_owner and prop.get("user_id") != caller_user_id:
        return {"error": "forbidden"}
    edits = edits or {}
    if action == "accept":
        # Owner can promote a `propose_shared=True` proposal into the shared
        # baseline (visible to everyone). Non-owner accepts always stay
        # private, even if the proposal asked for shared — the guardrail
        # is that only the owner curates J's public knowledge.
        share_it = bool(prop.get("propose_shared")) and is_owner
        await add_fact(
            db,
            user_id=prop.get("user_id") or caller_user_id,
            title=edits.get("title") or prop["title"],
            body=edits.get("body") or prop["body"],
            category=edits.get("category") or prop["category"],
            tags=edits.get("tags") or prop["tags"],
            source_url=edits.get("source_url", ""),
            source_query=prop.get("source", ""),
            signer="J+user",
            shared=share_it,
        )
        await db.knowledge_proposals.update_one(
            {"id": prop_id}, {"$set": {"status": "accepted"}},
        )
        return {"ok": True, "action": "accepted", "shared": share_it}
    if action == "reject":
        await db.knowledge_proposals.update_one(
            {"id": prop_id}, {"$set": {"status": "rejected"}},
        )
        return {"ok": True, "action": "rejected"}
    return {"error": f"unknown action: {action}"}


# ---------- Web search (Tavily) + auto-learn ---------------------------------


async def web_search(
    db,
    api_key: str,
    query: str,
    *,
    user_id: str,
    max_results: int = 5,
    include_answer: bool = True,
) -> dict[str, Any]:
    """Run a Tavily search, log it (scoped to `user_id`), return normalised JSON."""
    if not api_key:
        return {"error": "TAVILY_API_KEY not configured on the server."}
    if not (query or "").strip():
        return {"error": "empty query"}
    if not user_id:
        return {"error": "user_id required for web_search"}
    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=api_key)
        resp = await client.search(
            query=query,
            search_depth="advanced",
            max_results=max(1, min(int(max_results), 10)),
            include_answer=include_answer,
            include_raw_content=False,
            exclude_domains=["pinterest.com", "quora.com", "facebook.com"],
        )
    except Exception as e:
        return {"error": f"tavily failure: {type(e).__name__}: {str(e)[:200]}"}

    await db.knowledge_search_log.insert_one({
        "user_id": user_id,
        "query": query,
        "results_count": len(resp.get("results", []) or []),
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "query": query,
        "answer": (resp.get("answer") or "")[:2000],
        "results": [
            {
                "title": (r.get("title") or "")[:200],
                "url": r.get("url") or "",
                "content": (r.get("content") or "")[:1500],
                "score": r.get("score"),
            }
            for r in (resp.get("results") or [])
        ],
    }


async def auto_learn_from_search(
    db,
    search_result: dict[str, Any],
    *,
    user_id: str,
    shared: bool = False,
    llm_extract: "callable[str, str] | None" = None,
) -> dict[str, Any]:
    """Turn a Tavily search into 1..N durable facts scoped to `user_id`.

    Owner-triggered searches can pass `shared=True` to promote learned facts
    into J's public baseline. Non-owner searches always keep learned facts
    private (`shared=False`) so one user's browsing never surfaces for
    another user.

    If an `llm_extract(prompt) -> str` callable is supplied, we ask the LLM to
    distill the results into deduped, self-contained fact snippets. Otherwise
    we fall back to a deterministic 1-fact-per-result summariser.
    """
    if not user_id:
        return {"learned": 0, "error": "user_id required"}
    query = search_result.get("query", "")
    results = search_result.get("results") or []
    if not results:
        return {"learned": 0}

    category = guess_category(query)
    learned = 0

    if llm_extract:
        # LLM path — one call, JSON list of facts.
        joined = "\n\n".join(
            f"[{i+1}] {r.get('title')}\nURL: {r.get('url')}\n{r.get('content')[:800]}"
            for i, r in enumerate(results[:5])
        )
        prompt = (
            "Extract 1-5 DURABLE, self-contained facts from the search results "
            "below. Each fact must be usable months from now WITHOUT the search "
            "results still being open. Return ONLY strict JSON:\n"
            '{"facts":[{"title":"...","body":"1-3 sentence fact","source_url":"..."}]}\n\n'
            f"USER QUERY: {query}\n\n{joined}"
        )
        try:
            raw = await llm_extract(prompt)
            m = re.search(r"\{[\s\S]*\}", raw or "")
            if m:
                data = json.loads(m.group(0))
                for f in data.get("facts", [])[:5]:
                    r = await add_fact(
                        db,
                        user_id=user_id,
                        shared=shared,
                        title=f.get("title") or "",
                        body=f.get("body") or "",
                        category=category,
                        tags=[category, "auto"],
                        source_url=f.get("source_url") or "",
                        source_query=query,
                        signer="J:auto",
                    )
                    if r.get("ok") and not r.get("deduped"):
                        learned += 1
                return {"learned": learned, "category": category, "mode": "llm"}
        except Exception:
            pass  # fall through to deterministic

    # Deterministic fallback — one fact per top result, with quality gate.
    # Global scope means noise compounds: reject forum/community/social-style
    # titles, require decent content length, and prefer high-score Tavily hits.
    # Rejected candidates are NOT discarded — they get stashed in
    # `knowledge_dpo_candidates` as future DPO training material (chosen = a
    # kept fact, rejected = these forum/thin/low-score results).
    _JUNK_TITLE_TOKENS = (
        "forum", "community of", "reddit", "r/", "subreddit", "discussion",
        "youtube", "tiktok", "instagram", "facebook", "twitter",
    )
    kept_fact_ids: list[str] = []
    rejected_pool: list[dict] = []
    kept = 0
    for r in results[:5]:
        title = (r.get("title") or "").strip()
        body = (r.get("content") or "").strip()
        score = float(r.get("score") or 0.0)
        low_title = title.lower()

        # Decide accept vs reject; stash rejects for DPO regardless of quota.
        reject_reason = None
        if len(body) < 200:
            reject_reason = "body_too_short"
        elif score and score < 0.35:
            reject_reason = "low_tavily_score"
        elif any(t in low_title for t in _JUNK_TITLE_TOKENS):
            reject_reason = "junk_title"
        elif kept >= 3:
            reject_reason = "quota_exceeded"

        if reject_reason:
            rejected_pool.append({
                "title": title[:200],
                "body": body[:1500],
                "url": r.get("url", ""),
                "tavily_score": score,
                "reject_reason": reject_reason,
            })
            continue

        # Trim body to first ~800 chars but at a sentence boundary
        body_trim = body[:800]
        cut = body_trim.rfind(". ")
        if cut > 300:
            body_trim = body_trim[: cut + 1]
        add = await add_fact(
            db,
            user_id=user_id,
            shared=shared,
            title=title or query,
            body=body_trim,
            category=category,
            tags=[category, "auto"],
            source_url=r.get("url") or "",
            source_query=query,
            signer="J:auto",
        )
        if add.get("ok") and not add.get("deduped"):
            learned += 1
            kept += 1
            if add.get("id"):
                kept_fact_ids.append(add["id"])

    # Stash rejected candidates against every fact we kept — free DPO pairs.
    # Each rejected item is paired with each chosen fact from the same search,
    # so a single search with 3 chosen and 2 rejected yields 6 preference
    # rows. Storage is cheap; the training signal compounds.
    if rejected_pool and kept_fact_ids:
        now_iso = datetime.now(timezone.utc).isoformat()
        dpo_docs = []
        for chosen_id in kept_fact_ids:
            for rej in rejected_pool:
                dpo_docs.append({
                    "id": f"dpo_{uuid.uuid4().hex[:12]}",
                    "user_id": user_id,   # per-user scoping — same rule as facts
                    "shared": bool(shared),
                    "query": query,
                    "category": category,
                    "chosen_fact_id": chosen_id,
                    "rejected_title": rej["title"],
                    "rejected_body": rej["body"],
                    "rejected_url": rej["url"],
                    "rejected_tavily_score": rej["tavily_score"],
                    "reject_reason": rej["reject_reason"],
                    "ts": now_iso,
                })
        if dpo_docs:
            try:
                await db.knowledge_dpo_candidates.insert_many(dpo_docs, ordered=False)
            except Exception:
                pass  # non-critical — never let DPO stash break the learn path

    return {
        "learned": learned,
        "category": category,
        "mode": "deterministic",
        "dpo_pairs_stashed": len(rejected_pool) * len(kept_fact_ids)
        if rejected_pool and kept_fact_ids else 0,
    }


def format_recall_for_prompt(recalls: list[dict[str, Any]]) -> str:
    """Render a compact block J can consume in her system context per turn."""
    if not recalls:
        return ""
    lines = ["[J:MIND — relevant remembered facts]"]
    for r in recalls[:5]:
        src = f" (src: {r['source_url']})" if r.get("source_url") else ""
        lines.append(f"- ({r.get('score', 0):.2f}) [{r['category']}] {r['title']} — {r['body'][:280]}{src}")
    return "\n".join(lines)
