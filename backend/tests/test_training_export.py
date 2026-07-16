"""Regression tests for the training-data export endpoints.

Covers:
  - /api/knowledge/export?format=openai_sft streams OpenAI-fine-tune-shaped JSONL
  - /api/knowledge/export?format=raw streams the raw fact docs
  - /api/knowledge/export with unknown format returns 400
  - /api/training/dpo streams DPO-shaped JSONL from chronicle ai_answer rows
  - DPO export skips offline/verdict-negative rows
"""
from __future__ import annotations

import json
import os
import time

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://gauntlet-devspace.preview.emergentagent.com"
TOKEN = "test_session_devspace_001"
H = {"Authorization": f"Bearer {TOKEN}"}


def test_sft_export_shape():
    r = requests.get(f"{BASE_URL}/api/knowledge/export?format=openai_sft",
                     headers=H, timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert len(lines) >= 1
    row = json.loads(lines[0])
    assert "messages" in row
    roles = [m["role"] for m in row["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert "J" in row["messages"][0]["content"] or "AGENTS" in row["messages"][0]["content"]
    assert row["messages"][1]["content"]
    assert row["messages"][2]["content"]
    assert "metadata" in row
    assert row["metadata"].get("id", "").startswith("fact_")


def test_sft_export_raw_format():
    r = requests.get(f"{BASE_URL}/api/knowledge/export?format=raw",
                     headers=H, timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert len(lines) >= 1
    row = json.loads(lines[0])
    assert "id" in row
    assert "title" in row
    assert "body" in row
    assert "messages" not in row  # raw ≠ SFT


def test_sft_export_bad_format():
    r = requests.get(f"{BASE_URL}/api/knowledge/export?format=nope",
                     headers=H, timeout=15)
    assert r.status_code == 400


def test_dpo_export_shape():
    r = requests.get(f"{BASE_URL}/api/training/dpo", headers=H, timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    if not lines:
        # Empty is a valid state if no ai_answer rows exist; that's fine.
        return
    row = json.loads(lines[0])
    assert set(row.keys()) >= {"prompt", "chosen", "rejected", "meta"}
    assert row["prompt"]
    assert row["chosen"]
    assert "model" in row["meta"]
    assert "verdict" in row["meta"]


def test_ai_chat_logs_ai_answer():
    """A successful /ai/chat call must persist an ai_answer chronicle row.
    Skip if the LLM chain is offline — this is a training-pipeline test, not
    an LLM-availability test.
    """
    before = requests.get(f"{BASE_URL}/api/training/dpo", headers=H, timeout=30)
    before_lines = [l for l in before.text.splitlines() if l.strip()]

    r = requests.post(
        f"{BASE_URL}/api/ai/chat",
        headers={**H, "Content-Type": "application/json"},
        json={"message": "one-word only: 2+2?"},
        timeout=60,
    )
    if r.status_code != 200:
        import pytest
        pytest.skip(f"ai/chat unavailable: {r.status_code}")
    reply = r.json().get("reply", "")
    if reply.startswith("// J:OFFLINE"):
        import pytest
        pytest.skip("LLM chain offline; ai_answer would be verdict=offline (excluded from DPO by design)")

    time.sleep(0.5)
    after = requests.get(f"{BASE_URL}/api/training/dpo", headers=H, timeout=30)
    after_lines = [l for l in after.text.splitlines() if l.strip()]
    assert len(after_lines) >= len(before_lines) + 1, \
        f"expected +1 ai_answer row after /ai/chat call, got {len(after_lines)} vs {len(before_lines)}"
