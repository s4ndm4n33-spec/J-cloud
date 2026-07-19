"""In-process rate limiter — token-bucket per (user_id, scope).

Prevents accidental multi-fire (mashed Enter → 5 concurrent J calls) and
casual abuse without needing Redis or ingress-level middleware. Buckets live
in a module-level dict; when the pod restarts, buckets reset — that's fine,
this is a smoothing shield, not a hard billing gate. The daily-cap in
`llm_chain.chain_call` is the actual spend guardrail.

Usage:

    from core.ratelimit import take
    take(user_id, scope="ai", capacity=10, refill_per_sec=10/60)  # 10/min

Raises HTTPException(429) when the bucket is empty.
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Dict, Tuple

from fastapi import HTTPException

_buckets: Dict[Tuple[str, str], Tuple[float, float]] = {}  # (tokens, last_refill_ts)
_lock = Lock()

# Owner exempt — the owner is us and we bench-test heavily.
_OWNER_ID: str = ""


def set_owner_id(owner_id: str) -> None:
    global _OWNER_ID  # noqa: PLW0603
    _OWNER_ID = (owner_id or "").strip()


def take(user_id: str, scope: str, capacity: int, refill_per_sec: float,
         cost: float = 1.0) -> None:
    """Consume `cost` tokens from the (user_id, scope) bucket. Raise 429 if empty."""
    if _OWNER_ID and user_id == _OWNER_ID:
        return  # owner is exempt from client-side smoothing
    key = (user_id, scope)
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (float(capacity), now))
        # Refill proportional to elapsed time, capped at capacity.
        tokens = min(float(capacity), tokens + (now - last) * refill_per_sec)
        if tokens < cost:
            retry_in = max(0.0, (cost - tokens) / refill_per_sec) if refill_per_sec > 0 else 0.0
            _buckets[key] = (tokens, now)
            raise HTTPException(status_code=429, detail={
                "code": "rate_limited",
                "message": f"Slow down — {int(capacity * refill_per_sec * 60)} req/min cap on this endpoint.",
                "retry_in_seconds": round(retry_in, 1),
            })
        _buckets[key] = (tokens - cost, now)
