"""Recursive Temporal Persistence — Chronos Index + Associative Map + Heuristic Signature.

All three layers are code-driven and deterministic. No LLM involvement, no embedding
API calls (sub-millisecond retrieval requirement, per Carmack).

Storage layout:
  Per-project workspace : .shard/chronos.jsonl           (Intent-Store · Ritchie)
  MongoDB collection    : chronos_index                  (cross-workspace queries)
  MongoDB collection    : associative_vectors            (Stream-Buffer · Korotkevich)
  MongoDB collection    : heuristic_signature            (Personality sync per user)
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LEDGER_REL = ".shard/chronos.jsonl"

# Tokens that signal user engineering preferences for the Heuristic Signature.
SIGNAL_LEXICON = {
    "language_pref": {
        "go": ["golang", "goroutine", " go "],
        "python": ["pytest", "pep 8", "snake_case", "django", "flask"],
        "rust": ["cargo", "borrow checker", "tokio", "rustc"],
        "typescript": ["tsx", "type-safe", "tsc"],
        "powershell": ["pwsh", "ps1", "$env:", "Get-ChildItem"],
        "c": ["gcc", "make", "malloc"],
    },
    "philosophy": {
        "sovereignty": ["sovereign", "local", "offline", "self-host"],
        "minimalism": ["bloat", "lean", "minimal", "no deps"],
        "verifiable": ["verifiable", "audit", "deterministic", "signed"],
        "safety_first": ["migration_temp", "backup", "rollback", "halt"],
    },
    "sentiment": {
        "approval": ["nice", "perfect", "exactly", "love it", "ship it", "yes",
                     "excellent", "good", "great"],
        "rejection": ["no", "fuck", "wrong", "broken", "fucked", "ridiculous",
                      "bad", "stop", "revert"],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ledger_path(root: Path) -> Path:
    return root / LEDGER_REL


# ---------- 1. Chronos Index — The Ledger ----------


def chronos_append(project_root: Path, *, event_type: str, file: Optional[str] = None,
                   action: str, rationale: str = "", master: str = "",
                   sentiment: str = "neutral", actor: str = "J",
                   extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Append a structured event to the workspace's Chronos ledger.

    event_type examples: 'code_edit', 'tool_call', 'build', 'audit', 'decision',
                         'github', 'destructive_block', 'user_feedback'
    master: which of the Five Masters the action aligns with (Ritchie / Carmack / …)
    sentiment: 'approval' | 'rejection' | 'neutral'
    """
    p = _ledger_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now_iso(),
        "event_type": event_type,
        "file": file,
        "action": action,
        "rationale": rationale,
        "master": master,
        "sentiment": sentiment,
        "actor": actor,
    }
    if extra:
        entry["extra"] = extra
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def chronos_read(project_root: Path, *, limit: int = 200,
                 event_type: Optional[str] = None) -> list[dict[str, Any]]:
    p = _ledger_path(project_root)
    if not p.exists():
        return []
    entries: list[dict[str, Any]] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and e.get("event_type") != event_type:
                continue
            entries.append(e)
    return entries[-limit:]


# ---------- 2. Associative Vector Map — Stream-Buffer ----------


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "have", "has", "are", "was",
    "but", "not", "you", "your", "into", "out", "via", "use", "used", "using",
    "should", "would", "could", "will", "all", "any", "one", "two", "get", "got",
    "let", "set", "now", "can", "new", "old",
}


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")
            if w.lower() not in _STOPWORDS]


def _sparse_vec(text: str) -> dict[str, int]:
    """Term-frequency sparse vector (code-only, no ML deps)."""
    return dict(Counter(_tokenize(text)))


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def associative_record(db, user_id: str, *, project_id: str,
                              role: str, content: str, kind: str = "chat") -> None:
    """Index a conversation/tool/event chunk for later recall.

    Stored as TF vector + raw text. Memory-mapped retrieval via Mongo index.
    """
    vec = _sparse_vec(content)
    if not vec:
        return
    await db.associative_vectors.insert_one({
        "user_id": user_id,
        "project_id": project_id,
        "role": role,            # 'user' | 'assistant' | 'tool' | 'audit' | …
        "kind": kind,
        "content": content[:2000],
        "vec": vec,
        "ts": _now_iso(),
    })


async def associative_recall(db, user_id: str, *, query: str, k: int = 5,
                              project_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Return top-K most semantically-similar prior chunks. Pure cosine on TF."""
    qvec = _sparse_vec(query)
    if not qvec:
        return []
    flt: dict[str, Any] = {"user_id": user_id}
    if project_id:
        flt["project_id"] = project_id
    cursor = db.associative_vectors.find(flt, {"_id": 0}).sort("ts", -1).limit(500)
    candidates = await cursor.to_list(500)
    scored = [
        (_cosine(qvec, c.get("vec") or {}), c) for c in candidates
    ]
    scored = [s for s in scored if s[0] > 0.05]
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, c in scored[:k]:
        c.pop("vec", None)
        c["score"] = round(score, 3)
        out.append(c)
    return out


# ---------- 3. Heuristic Signature — Personality sync ----------


def _scan_signals(text: str) -> dict[str, dict[str, int]]:
    """Count signal lexicon hits in text."""
    low = (text or "").lower()
    out: dict[str, dict[str, int]] = {}
    for category, options in SIGNAL_LEXICON.items():
        bucket = out.setdefault(category, {})
        for key, needles in options.items():
            hits = sum(low.count(n.lower()) for n in needles)
            if hits:
                bucket[key] = hits
    return out


async def heuristic_update(db, user_id: str, text: str) -> None:
    """Increment heuristic counters from the user's message text."""
    signals = _scan_signals(text)
    if not signals:
        return
    inc_doc: dict[str, int] = {}
    for category, bucket in signals.items():
        for key, hits in bucket.items():
            inc_doc[f"counters.{category}.{key}"] = hits
    inc_doc["counters._total_messages"] = 1
    await db.heuristic_signature.update_one(
        {"user_id": user_id},
        {"$inc": inc_doc, "$set": {"updated_at": _now_iso()}},
        upsert=True,
    )


async def heuristic_get(db, user_id: str) -> dict[str, Any]:
    doc = await db.heuristic_signature.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return {"counters": {}, "summary": {}, "exists": False}
    counters = doc.get("counters", {})
    summary: dict[str, str] = {}
    # Pick the dominant key in each category (excluding internal _total_messages)
    for cat in ("language_pref", "philosophy", "sentiment"):
        bucket = counters.get(cat, {}) if isinstance(counters.get(cat), dict) else {}
        if not bucket:
            continue
        top = max(bucket.items(), key=lambda kv: kv[1])
        summary[cat] = top[0]
    return {"counters": counters, "summary": summary,
            "updated_at": doc.get("updated_at"), "exists": True}


def render_signature(sig: dict[str, Any]) -> str:
    """Render the heuristic signature as a compact prompt fragment for J."""
    if not sig.get("exists"):
        return ""
    s = sig.get("summary", {})
    parts = []
    if "language_pref" in s:
        parts.append(f"prefers {s['language_pref']}")
    if "philosophy" in s:
        parts.append(f"values {s['philosophy']}")
    if "sentiment" in s:
        parts.append(f"recent sentiment: {s['sentiment']}")
    if not parts:
        return ""
    return "User Heuristic Signature: " + "; ".join(parts) + "."
