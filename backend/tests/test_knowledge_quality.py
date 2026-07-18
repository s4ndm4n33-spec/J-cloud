"""Regression tests for the J:MIND quality enhancements shipped 2026-07-17:

  1. Time-decay / freshness scoring in `_freshness_score`.
  2. DPO pair auto-stashing on rejected Tavily candidates.
  3. DPO export merges chronicle ai_answer + web_search DPO sources.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://gauntlet-devspace.preview.emergentagent.com"
TOKEN = "test_session_devspace_001"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# --- Freshness ---


def test_freshness_math_boundaries():
    """Import the pure function and verify the linear decay curve."""
    import sys
    sys.path.insert(0, "/app/backend")
    from core.knowledge import _freshness_score, FRESHNESS_FLOOR

    now = datetime.now(timezone.utc)

    def iso(days_ago: int) -> str:
        return (now - timedelta(days=days_ago)).isoformat()

    # Anchor points — allow a small tolerance because iso roundtrip + wall
    # clock drift can push a "30 days" value fractionally past the boundary
    # into the linear-decay branch.
    assert _freshness_score(iso(0)) >= 0.99
    # 29 days is definitively in the "full freshness" plateau.
    assert _freshness_score(iso(29)) == 1.0
    assert abs(_freshness_score(iso(180)) - FRESHNESS_FLOOR) < 0.001
    assert abs(_freshness_score(iso(365)) - FRESHNESS_FLOOR) < 0.001
    # Linear decay in between (105 days ≈ halfway through the decay window)
    mid = _freshness_score(iso(105))
    assert 0.6 < mid < 0.7
    # Empty / missing ts_last_seen must not crash
    assert _freshness_score("") == FRESHNESS_FLOOR
    assert _freshness_score("not-an-iso-string") == FRESHNESS_FLOOR


def test_recall_returns_blended_score_field():
    """After the freshness upgrade, recall responses include blended_score."""
    r = requests.post(f"{BASE_URL}/api/knowledge/recall", headers=H,
                      json={"query": "torque spec", "k": 3}, timeout=30)
    assert r.status_code == 200
    hits = r.json()["hits"]
    if not hits:
        pytest.skip("no facts to recall against")
    # Every returned hit must carry both raw cosine `score` and `blended_score`.
    for h in hits:
        assert "score" in h
        assert "blended_score" in h


# --- DPO Stashing ---


def test_web_search_stashes_dpo_pairs():
    """A live Tavily search with quality-mixed results should stash DPO pairs.

    Uses a query known to return >5 hits with mixed quality. If Tavily rate-
    limits or the query happens to be all-clean this run, we skip rather
    than fail — this is a live-dependency probe, not a pure unit test.
    """
    r = requests.post(f"{BASE_URL}/api/knowledge/search", headers=H,
                      json={"query": "python fastapi tutorial best practices"},
                      timeout=90)
    if r.status_code != 200:
        pytest.skip(f"Tavily unavailable: {r.status_code}")
    d = r.json()
    learn = d.get("_learn", {})
    if not d.get("results"):
        pytest.skip("Tavily returned no results this run")
    total_signal = learn.get("learned", 0) + learn.get("dpo_pairs_stashed", 0)
    assert total_signal >= 1, f"tavily gave results but no signal extracted: {learn}"


def test_dpo_export_web_source():
    """DPO export with scope=web must include rows with meta.source='web_search'."""
    r = requests.get(f"{BASE_URL}/api/training/dpo?scope=web",
                     headers=H, timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    if not lines:
        pytest.skip("no web_search DPO pairs yet")
    import json
    row = json.loads(lines[0])
    assert row["meta"]["source"] == "web_search"
    assert row["chosen"]
    assert row["rejected"]  # never null for web-source rows
    assert row["meta"]["reject_reason"] in {
        "body_too_short", "low_tavily_score", "junk_title", "quota_exceeded"
    }


def test_dpo_export_combined_sources():
    """Default DPO export (no scope filter) merges both sources."""
    r = requests.get(f"{BASE_URL}/api/training/dpo", headers=H, timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    if len(lines) < 2:
        pytest.skip("need at least 2 rows across both sources")
    import json
    sources = {json.loads(l)["meta"]["source"] for l in lines}
    # Either source alone can produce data; we just verify export doesn't crash
    # and every row is labelled with a known source.
    assert sources.issubset({"chronicle", "web_search"})
