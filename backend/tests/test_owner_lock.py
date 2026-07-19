"""P0 Owner-Only Lock — regression tests.

Ensures shared EMERGENT_LLM_KEY and TAVILY_API_KEY are only consumable by
the app owner (identified by OWNER_USER_ID env var). Non-owners must BYOK.

Owner session:      Bearer test_owner_session_001   (user_5d2818f635a9)
Non-owner session:  Bearer test_session_devspace_001 (user_test_devspace)
"""
from __future__ import annotations

import os

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL",
                      "http://localhost:8001").rstrip("/")
OWNER_H = {"Authorization": "Bearer test_owner_session_001",
           "Content-Type": "application/json"}
GUEST_H = {"Authorization": "Bearer test_session_devspace_001",
           "Content-Type": "application/json"}


# ---------- /ai/chain ----------

def test_chain_owner_sees_universal_runnable():
    r = requests.get(f"{BASE}/api/ai/chain", headers=OWNER_H, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["is_owner"] is True
    chat = j["chains"]["chat"]
    universals = [s for s in chat if s["source"] == "universal"]
    assert universals and universals[0]["runnable"] is True


def test_chain_guest_universal_is_skip():
    r = requests.get(f"{BASE}/api/ai/chain", headers=GUEST_H, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["is_owner"] is False
    for task in ("chat", "refine", "governance"):
        universals = [s for s in j["chains"][task] if s["source"] == "universal"]
        assert universals, f"missing universal step in {task}"
        assert universals[0]["runnable"] is False, \
            f"{task}: universal must be SKIP for non-owner"


# ---------- /ai/chat ----------

def test_chat_guest_gets_401_needs_keys():
    r = requests.post(f"{BASE}/api/ai/chat", headers=GUEST_H,
                      json={"message": "hi"}, timeout=30)
    assert r.status_code == 401, r.text
    d = r.json()["detail"]
    assert d["code"] == "needs_keys"
    # Every attempt must be a skip — nothing was actually spent
    for a in d.get("attempts", []):
        assert a["status"] == "skipped"


def test_chat_owner_succeeds():
    r = requests.post(f"{BASE}/api/ai/chat", headers=OWNER_H,
                      json={"message": "Reply with exactly the word: pong"},
                      timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["meta"]["success"] is True
    assert j["reply"]


# ---------- /ai/refine ----------

def test_refine_guest_401():
    r = requests.post(f"{BASE}/api/ai/refine", headers=GUEST_H,
                      json={"code": "def f():\n    return 1\n",
                            "instruction": "add docstring",
                            "language": "python"}, timeout=30)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "needs_keys"


# ---------- /knowledge/search ----------

def test_knowledge_search_guest_401():
    r = requests.post(f"{BASE}/api/knowledge/search", headers=GUEST_H,
                      json={"query": "test"}, timeout=15)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "needs_tavily_key"


def test_knowledge_search_owner_200():
    r = requests.post(f"{BASE}/api/knowledge/search", headers=OWNER_H,
                      json={"query": "python typing generic",
                            "max_results": 2, "learn": False}, timeout=30)
    # Tavily can 502 if the network is flaky; we just want to verify the
    # owner-lock did NOT block us with a 401.
    assert r.status_code != 401, r.text


# ---------- /ai/agent (agent loop) ----------

def test_agent_guest_401(mongo_seeded_project):
    """Non-owner should be blocked at the first turn of the agent loop."""
    project_id = mongo_seeded_project
    r = requests.post(f"{BASE}/api/ai/agent", headers=GUEST_H,
                      json={"project_id": project_id, "message": "ping",
                            "max_steps": 1}, timeout=30)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "needs_keys"


# ---------- Fixture: seed a project for the non-owner ----------

@pytest.fixture
def mongo_seeded_project():
    """Insert a project row for user_test_devspace so /ai/agent doesn't 404."""
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    async def _seed():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        pid = "proj_owner_lock_test"
        await db.projects.update_one(
            {"project_id": pid, "user_id": "user_test_devspace"},
            {"$set": {"project_id": pid, "user_id": "user_test_devspace",
                      "name": "owner-lock-test"}},
            upsert=True,
        )
        return pid

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_seed())
    finally:
        loop.close()
