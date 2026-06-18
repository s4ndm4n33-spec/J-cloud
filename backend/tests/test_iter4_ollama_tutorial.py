"""
Iter4 backend tests
Covers:
  - /api/settings/keys GET: 4 providers (openai, anthropic, gemini, ollama) + ollama_presets
  - /api/settings/keys PUT for cloud: validation & masking
  - /api/settings/keys PUT for ollama: base_url + default_model rules
  - /api/settings/keys/ollama/test contract (no real ollama needed)
  - /api/settings/keys DELETE ollama
  - /api/ai/chain shows 5-step chains with ollama LAST and runnable only when configured
  - /api/me/tutorial GET/POST
  - /api/auth/logout invalidates session row when only Bearer is sent (iter3 MEDIUM gap fix)
"""

import os
import requests
import pytest

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "https://gauntlet-devspace.preview.emergentagent.com"
).rstrip("/")
TOKEN = "test_session_devspace_001"


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    return sess


@pytest.fixture(autouse=True)
def cleanup_ollama_and_reset_tutorial(s):
    """Each test starts with no ollama key + tutorial reset to False."""
    s.delete(f"{BASE_URL}/api/settings/keys/ollama")
    s.post(f"{BASE_URL}/api/me/tutorial", json={"completed": False})
    yield


# ---------- SETTINGS GET ----------

class TestSettingsKeysGet:
    def test_returns_four_providers_with_ollama_presets(self, s):
        r = s.get(f"{BASE_URL}/api/settings/keys")
        assert r.status_code == 200
        data = r.json()
        provs = [p["provider"] for p in data["providers"]]
        assert set(provs) == {"openai", "anthropic", "gemini", "ollama"}
        # Presets
        assert "ollama_presets" in data
        assert data["ollama_presets"].get("ollama") == "http://localhost:11434"
        assert data["ollama_presets"].get("llama-cpp") == "http://localhost:8080"

    def test_ollama_entry_has_base_url_and_default_model_fields(self, s):
        r = s.get(f"{BASE_URL}/api/settings/keys")
        ollama = next(p for p in r.json()["providers"] if p["provider"] == "ollama")
        assert "base_url" in ollama
        assert "default_model" in ollama
        assert ollama["configured"] is False
        assert ollama["base_url"] == ""
        assert ollama["default_model"] == ""


# ---------- SETTINGS PUT (CLOUD) ----------

class TestCloudKeyPut:
    def test_valid_cloud_key_saved_and_masked(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "openai", "api_key": "sk-test-1234567890"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["provider"] == "openai"
        # Masked must not be the raw key
        assert body["masked"]
        assert "sk-test-1234567890" not in body["masked"]
        # Cleanup
        s.delete(f"{BASE_URL}/api/settings/keys/openai")

    def test_short_cloud_key_rejected(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "openai", "api_key": "tooshort"},
        )
        assert r.status_code == 400

    def test_missing_cloud_key_rejected(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "anthropic"},
        )
        assert r.status_code == 400


# ---------- SETTINGS PUT (OLLAMA) ----------

class TestOllamaKeyPut:
    def test_valid_ollama_saves_with_masked_pair(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "default_model": "llama3.1",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["masked"] == "http://localhost:11434 · llama3.1"

    def test_get_after_save_returns_configured_with_fields(self, s):
        s.put(
            f"{BASE_URL}/api/settings/keys",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "default_model": "llama3.1",
            },
        )
        r = s.get(f"{BASE_URL}/api/settings/keys")
        ollama = next(p for p in r.json()["providers"] if p["provider"] == "ollama")
        assert ollama["configured"] is True
        assert ollama["base_url"] == "http://localhost:11434"
        assert ollama["default_model"] == "llama3.1"
        assert ollama["masked"] == "http://localhost:11434 · llama3.1"

    def test_missing_base_url_rejected(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "ollama", "default_model": "llama3.1"},
        )
        assert r.status_code == 400

    def test_missing_default_model_rejected(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "ollama", "base_url": "http://localhost:11434"},
        )
        assert r.status_code == 400

    def test_invalid_base_url_scheme_rejected(self, s):
        r = s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "ollama", "base_url": "localhost:11434", "default_model": "llama3.1"},
        )
        assert r.status_code == 400

    def test_delete_ollama_clears_configured(self, s):
        s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "ollama", "base_url": "http://localhost:11434", "default_model": "llama3.1"},
        )
        r = s.delete(f"{BASE_URL}/api/settings/keys/ollama")
        assert r.status_code == 200
        r2 = s.get(f"{BASE_URL}/api/settings/keys")
        ollama = next(p for p in r2.json()["providers"] if p["provider"] == "ollama")
        assert ollama["configured"] is False


# ---------- OLLAMA TEST CONNECTION ----------

class TestOllamaTestEndpoint:
    def test_unreachable_url_returns_ok_false(self, s):
        r = s.post(
            f"{BASE_URL}/api/settings/keys/ollama/test",
            json={"base_url": "http://127.0.0.1:6"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is False
        assert "error" in body

    def test_invalid_scheme_returns_400(self, s):
        r = s.post(
            f"{BASE_URL}/api/settings/keys/ollama/test",
            json={"base_url": "not-a-url"},
        )
        assert r.status_code == 400


# ---------- /ai/chain ----------

class TestAiChain:
    def test_five_step_chains_ollama_last(self, s):
        r = s.get(f"{BASE_URL}/api/ai/chain")
        assert r.status_code == 200
        chains = r.json()["chains"]
        for task in ("chat", "refine", "governance"):
            assert task in chains
            steps = chains[task]
            assert len(steps) == 5, f"{task} should have 5 steps"
            assert steps[-1]["provider"] == "ollama", f"{task} last step must be ollama"

    def test_ollama_runnable_false_when_not_configured(self, s):
        r = s.get(f"{BASE_URL}/api/ai/chain")
        for task, steps in r.json()["chains"].items():
            assert steps[-1]["runnable"] is False, f"{task} ollama should be SKIP when not configured"

    def test_ollama_runnable_true_after_save(self, s):
        s.put(
            f"{BASE_URL}/api/settings/keys",
            json={"provider": "ollama", "base_url": "http://localhost:11434", "default_model": "llama3.1"},
        )
        r = s.get(f"{BASE_URL}/api/ai/chain")
        for task, steps in r.json()["chains"].items():
            assert steps[-1]["runnable"] is True
            # model now reflects user-default substitution
            assert steps[-1]["model"] == "llama3.1"


# ---------- TUTORIAL STATE ----------

class TestTutorialState:
    def test_get_returns_false_after_reset(self, s):
        r = s.get(f"{BASE_URL}/api/me/tutorial")
        assert r.status_code == 200
        assert r.json()["completed"] is False

    def test_post_true_then_get_reflects(self, s):
        r = s.post(f"{BASE_URL}/api/me/tutorial", json={"completed": True})
        assert r.status_code == 200
        assert r.json()["completed"] is True
        r2 = s.get(f"{BASE_URL}/api/me/tutorial")
        assert r2.json()["completed"] is True

    def test_post_false_then_get_reflects(self, s):
        s.post(f"{BASE_URL}/api/me/tutorial", json={"completed": True})
        r = s.post(f"{BASE_URL}/api/me/tutorial", json={"completed": False})
        assert r.status_code == 200
        assert r.json()["completed"] is False
        r2 = s.get(f"{BASE_URL}/api/me/tutorial")
        assert r2.json()["completed"] is False


# ---------- LOGOUT BEARER-ONLY (iter3 MEDIUM fix) ----------

class TestLogoutBearerInvalidates:
    """The iter3 MEDIUM gap: logout with Bearer-only must delete server session row."""

    def test_bearer_only_logout_invalidates_session_then_reseed(self, s):
        # Create a short-lived second session row so we don't kill the shared TOKEN
        # used by other tests in this session. We do this by hitting the seed endpoint
        # if available, OR by reusing TOKEN and re-seeding via mongosh through Python.
        # Simpler: use the shared TOKEN, run logout, verify 401, then re-seed via the
        # /auth/session emergent-id path is not available in test env, so we re-insert
        # the session row by calling an internal seed helper. Since this test env
        # has no such helper, we reuse a dedicated mongo connection.
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from datetime import datetime, timezone, timedelta

        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")

        async def reseed():
            cli = AsyncIOMotorClient(mongo_url)
            d = cli[db_name]
            await d.user_sessions.delete_many({"session_token": TOKEN})
            await d.user_sessions.insert_one({
                "user_id": "user_test_devspace",
                "session_token": TOKEN,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            cli.close()

        # Step 1: Verify Bearer works
        r0 = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r0.status_code == 200

        # Step 2: Logout with Bearer ONLY (no cookie)
        r1 = requests.post(
            f"{BASE_URL}/api/auth/logout",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r1.status_code == 200
        assert r1.json().get("ok") is True

        # Step 3: Same Bearer should now be 401
        r2 = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r2.status_code == 401, "Server-side session not invalidated on Bearer-only logout"

        # Step 4: Re-seed so subsequent tests keep working (this test
        # is intentionally placed in its own class — but be defensive).
        asyncio.run(reseed())

        # Verify re-seed succeeded
        r3 = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r3.status_code == 200
