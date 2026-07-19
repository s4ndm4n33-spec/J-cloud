"""
Iter5 backend tests — Private Mode toggle

Covers:
  - GET  /api/me/private-mode returns {enabled, ollama_ready}
  - POST /api/me/private-mode {enabled:true} requires ollama configured
       * 400 + specific error message when not configured
       * 200 + persists when configured
  - POST /api/me/private-mode {enabled:false} always 200, clears flag
  - GET  /api/ai/chain returns top-level `private_mode` boolean
       * non-ollama steps runnable:false when private_mode=true
       * only ollama runnable when configured + private_mode=true
  - /api/ai/chat with private_mode=true filters meta.attempts to ollama only
       (chain typically returns success=false in test env w/o real Ollama;
        the key assertion is that NO non-ollama provider appears in attempts)
"""

import asyncio
import os
import requests
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "https://gauntlet-devspace.preview.emergentagent.com"
).rstrip("/")
TOKEN = "test_owner_session_001"
USER_ID = "user_5d2818f635a9"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    return sess


async def _reset_user_state():
    """Clear ollama BYOK + private_mode flag directly in Mongo for clean test state."""
    cli = AsyncIOMotorClient(MONGO_URL)
    d = cli[DB_NAME]
    await d.user_provider_keys.delete_many({"user_id": USER_ID, "provider": "ollama"})
    await d.users.update_one(
        {"user_id": USER_ID},
        {"$set": {"private_mode": False}},
    )
    cli.close()


@pytest.fixture(autouse=True)
def reset_state(s):
    """Each test starts with no ollama linked + private_mode=False."""
    asyncio.run(_reset_user_state())
    yield
    # Clear test state again so next test's setup is deterministic
    asyncio.run(_reset_user_state())


@pytest.fixture(scope="module", autouse=True)
def restore_baseline_after_module(s):
    """After this module finishes, restore main-agent's baseline:
    ollama linked (http://localhost:11434, llama3.1) + private_mode=False.
    This matches the env state described in the review request."""
    yield
    asyncio.run(_reset_user_state())
    try:
        s.put(
            f"{BASE_URL}/api/settings/keys",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "default_model": "llama3.1",
            },
        )
    except Exception:
        pass


def _link_ollama(s):
    return s.put(
        f"{BASE_URL}/api/settings/keys",
        json={
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "default_model": "llama3.1",
        },
    )


# ---------- GET /api/me/private-mode ----------

class TestGetPrivateMode:
    def test_returns_disabled_and_ollama_not_ready_when_unconfigured(self, s):
        r = s.get(f"{BASE_URL}/api/me/private-mode")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["ollama_ready"] is False

    def test_ollama_ready_true_only_when_both_base_url_and_model_saved(self, s):
        assert _link_ollama(s).status_code == 200
        r = s.get(f"{BASE_URL}/api/me/private-mode")
        body = r.json()
        assert body["enabled"] is False
        assert body["ollama_ready"] is True


# ---------- POST /api/me/private-mode ----------

class TestSetPrivateMode:
    def test_enable_without_ollama_returns_400_with_message_and_does_not_persist(self, s):
        r = s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Link a local server" in detail
        assert "Ollama" in detail or "llama.cpp" in detail
        # Verify NOT persisted
        check = s.get(f"{BASE_URL}/api/me/private-mode").json()
        assert check["enabled"] is False

    def test_enable_with_ollama_returns_200_and_persists(self, s):
        assert _link_ollama(s).status_code == 200
        r = s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["enabled"] is True
        # Re-GET confirms persistence
        check = s.get(f"{BASE_URL}/api/me/private-mode").json()
        assert check["enabled"] is True
        assert check["ollama_ready"] is True

    def test_disable_always_returns_200_even_without_ollama(self, s):
        # No ollama linked, but disabling should not be gated
        r = s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_disable_clears_previously_enabled_flag(self, s):
        assert _link_ollama(s).status_code == 200
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        r = s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        check = s.get(f"{BASE_URL}/api/me/private-mode").json()
        assert check["enabled"] is False


# ---------- /api/ai/chain reflects private_mode ----------

class TestAiChainPrivateMode:
    def test_chain_returns_private_mode_false_by_default(self, s):
        r = s.get(f"{BASE_URL}/api/ai/chain")
        assert r.status_code == 200
        data = r.json()
        assert "private_mode" in data
        assert data["private_mode"] is False

    def test_chain_returns_private_mode_true_after_enable(self, s):
        _link_ollama(s)
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        r = s.get(f"{BASE_URL}/api/ai/chain")
        data = r.json()
        assert data["private_mode"] is True

    def test_non_ollama_steps_are_not_runnable_under_private_mode(self, s):
        _link_ollama(s)
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        data = s.get(f"{BASE_URL}/api/ai/chain").json()
        for task, steps in data["chains"].items():
            ollama_steps = [st for st in steps if st["provider"] == "ollama"]
            non_ollama = [st for st in steps if st["provider"] != "ollama"]
            assert ollama_steps, f"{task} has no ollama step"
            # Every non-ollama step must be SKIP
            for st in non_ollama:
                assert st["runnable"] is False, (
                    f"{task} step {st} should be SKIP under private_mode"
                )
            # ollama step should be runnable (ollama is configured)
            for st in ollama_steps:
                assert st["runnable"] is True, (
                    f"{task} ollama should be ARMED under private_mode + configured"
                )

    def test_disabling_private_mode_restores_runnable_universal(self, s):
        _link_ollama(s)
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": False})
        data = s.get(f"{BASE_URL}/api/ai/chain").json()
        assert data["private_mode"] is False
        # Universal steps should be runnable again (EMERGENT_LLM_KEY is present in env)
        any_universal_runnable = False
        for steps in data["chains"].values():
            for st in steps:
                if st["source"] == "universal" and st["runnable"]:
                    any_universal_runnable = True
        assert any_universal_runnable, (
            "After disabling private_mode, at least one universal step should be runnable"
        )


# ---------- /api/ai/chat under private_mode ----------

class TestAiChatPrivateMode:
    def test_chat_attempts_contain_only_ollama_when_private_mode_on(self, s):
        _link_ollama(s)
        s.post(f"{BASE_URL}/api/me/private-mode", json={"enabled": True})

        r = s.post(
            f"{BASE_URL}/api/ai/chat",
            json={"message": "ping", "files": [], "conversation_id": None},
            timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        meta = body.get("meta", {})
        attempts = meta.get("attempts", [])
        # Allow zero attempts only if chain was somehow empty; we expect at least one
        assert len(attempts) > 0, "Expected at least one ollama attempt under private_mode"
        for a in attempts:
            assert a["provider"] == "ollama", (
                f"Non-ollama provider leaked into private-mode attempts: {a}"
            )
        # In the test env, no real Ollama is reachable → success should be False
        # and the reply should be the offline message.
        if meta.get("success") is False:
            assert "OFFLINE" in body.get("reply", "")
