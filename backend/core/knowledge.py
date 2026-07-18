"""J's Mind — a global, persistent knowledge store with semantic recall.

Two tiers, one goal:

    Tier 1 — `knowledge_facts` (MongoDB, keyword+tag searchable, embedded).
             The durable memory. J writes here; every user reads.
    Tier 2 — `knowledge_proposals` (MongoDB, pending-approval queue).
             Insights J *thinks* are worth remembering but haven't been
             confirmed by a human yet.

Auto-learn: after every `web_search`, J summarises the top hits into a
handful of durable facts (via LLM) and stores them WITHOUT approval — a URL
source and category tag give us provenance. This is the "learn from web"
loop the user asked for.

Opt-in: `propose_learning(insight)` creates a proposal instead of writing
straight to the fact table. The user gets a MIND panel to ACCEPT / EDIT /
REJECT. This is the "learn from conversation" loop.

Retrieval: `recall(query, k)` uses fastembed cosine similarity for semantic
recall, falling back to Mongo text search when embeddings aren't available.
Injected into the agent's system context per turn so J's answers get sharper
as the store grows.

Scope: global (per user's explicit choice). One typo doesn't ruin the store
because facts carry source URLs; the frontend surfaces them and users can
delete anything questionable.
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
    await db.knowledge_proposals.create_index([("id", 1)], unique=True)
    await db.knowledge_proposals.create_index([("status", 1), ("ts", -1)])
    await db.knowledge_search_log.create_index([("ts", -1)])
    # DPO candidates: rejected Tavily results kept for preference-pair training.
    await db.knowledge_dpo_candidates.create_index([("ts", -1)])
    await db.knowledge_dpo_candidates.create_index([("chosen_fact_id", 1)])


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
    title: str,
    body: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    source_url: str = "",
    source_query: str = "",
    signer: str = "J",
    embed_now: bool = True,
) -> dict[str, Any]:
    """Insert or upsert a fact. De-dup on (source_url, title) if source_url set."""
    title = (title or "").strip()[:200]
    body = (body or "").strip()[:6000]
    if not title or not body:
        return {"error": "title and body required"}
    category = (category or "general").strip().lower() or "general"
    tags_clean = [str(t).lower().strip()[:32] for t in (tags or []) if str(t).strip()][:8]

    # De-dup: if a fact from the same URL+title already exists, bump ref_count.
    if source_url:
        prior = await db.knowledge_facts.find_one(
            {"source_url": source_url, "title": title}, {"_id": 0}
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
    category: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if category:
        query["category"] = category
    if tag:
        query["tags"] = tag
    if q:
        query["$text"] = {"$search": q}
    docs = await db.knowledge_facts.find(query, {"_id": 0, "embedding": 0}) \
        .sort("ts", -1).to_list(int(limit))
    return docs


async def delete_fact(db, fact_id: str) -> dict[str, Any]:
    r = await db.knowledge_facts.delete_one({"id": fact_id})
    return {"ok": r.deleted_count == 1}


# ---------- Semantic recall ---------------------------------------------------


async def recall(
    db,
    query: str,
    *,
    k: int = 5,
    category: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return top-K facts most relevant to `query`.

    Path A (embeddings available): cosine similarity over stored vectors.
    Path B (fallback): Mongo `$text` search — no embeddings needed.
    """
    q = (query or "").strip()
    if not q:
        return []
    base_filter: dict[str, Any] = {"embedding": {"$ne": None}}
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
        "status": "pending",  # pending | accepted | rejected
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.knowledge_proposals.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_proposals(db, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
    docs = await db.knowledge_proposals.find(
        {"status": status}, {"_id": 0}
    ).sort("ts", -1).to_list(int(limit))
    return docs


async def resolve_proposal(
    db, prop_id: str, action: str,
    edits: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    prop = await db.knowledge_proposals.find_one({"id": prop_id}, {"_id": 0})
    if not prop:
        return {"error": "not found"}
    edits = edits or {}
    if action == "accept":
        await add_fact(
            db,
            title=edits.get("title") or prop["title"],
            body=edits.get("body") or prop["body"],
            category=edits.get("category") or prop["category"],
            tags=edits.get("tags") or prop["tags"],
            source_url=edits.get("source_url", ""),
            source_query=prop.get("source", ""),
            signer="J+user",
        )
        await db.knowledge_proposals.update_one(
            {"id": prop_id}, {"$set": {"status": "accepted"}},
        )
        return {"ok": True, "action": "accepted"}
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
    max_results: int = 5,
    include_answer: bool = True,
) -> dict[str, Any]:
    """Run a Tavily search, log it, and return normalised JSON."""
    if not api_key:
        return {"error": "TAVILY_API_KEY not configured on the server."}
    if not (query or "").strip():
        return {"error": "empty query"}
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
    llm_extract: "callable[str, str] | None" = None,
) -> dict[str, Any]:
    """Turn a Tavily search into 1..N durable facts.

    If an `llm_extract(prompt) -> str` callable is supplied, we ask the LLM to
    distill the results into deduped, self-contained fact snippets. Otherwise
    we fall back to a deterministic 1-fact-per-result summariser.
    """
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
