"""Backend tests for Groq + OpenRouter BYOK addition (iteration 13)."""
import os
import re
import requests
import pytest
from pathlib import Path

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        env = Path("/app/frontend/.env").read_text()
        for line in env.splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
                break
    assert url, "REACT_APP_BACKEND_URL not set"
    return url.rstrip("/")

BASE_URL = _load_backend_url()
OWNER_TOKEN = "test_owner_session_001"
HEADERS = {"Authorization": f"Bearer {OWNER_TOKEN}", "Content-Type": "application/json"}


# --- GET /settings/keys should include groq + openrouter ---
def test_list_keys_includes_groq_and_openrouter():
    r = requests.get(f"{BASE_URL}/api/settings/keys", headers=HEADERS, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    providers = [p["provider"] for p in data.get("providers", [])]
    assert "groq" in providers, f"groq missing: {providers}"
    assert "openrouter" in providers, f"openrouter missing: {providers}"
    # Legacy providers still present
    for p in ("openai", "anthropic", "gemini", "ollama"):
        assert p in providers, f"{p} missing: {providers}"


# --- validate endpoint: groq with garbage key ---
def test_validate_groq_garbage_key_returns_ok_false():
    r = requests.post(
        f"{BASE_URL}/api/settings/keys/validate",
        headers=HEADERS,
        json={"provider": "groq", "api_key": "gsk_garbage_invalid_key_1234567890"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is False
    assert data.get("provider") == "groq"
    assert "Groq" in (data.get("message") or ""), data


# --- validate endpoint: openrouter with garbage key ---
def test_validate_openrouter_garbage_key_returns_ok_false():
    r = requests.post(
        f"{BASE_URL}/api/settings/keys/validate",
        headers=HEADERS,
        json={"provider": "openrouter", "api_key": "sk-or-garbage-invalid-key-1234567890"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is False
    assert data.get("provider") == "openrouter"
    assert "OpenRouter" in (data.get("message") or ""), data


# --- validate endpoint: unknown provider → 400 ---
def test_validate_unknown_provider_returns_400():
    r = requests.post(
        f"{BASE_URL}/api/settings/keys/validate",
        headers=HEADERS,
        json={"provider": "cohere", "api_key": "some-key-value-here-12345"},
        timeout=15,
    )
    assert r.status_code == 400
    assert "Unsupported provider" in r.text


# --- validate endpoint: short key returns ok:false, not 400 ---
def test_validate_groq_short_key():
    r = requests.post(
        f"{BASE_URL}/api/settings/keys/validate",
        headers=HEADERS,
        json={"provider": "groq", "api_key": "short"},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json().get("ok") is False


# --- Source inspection: llm_chain module wiring ---
def test_llm_chain_source_wiring():
    path = "/app/backend/llm_chain.py"
    src = open(path).read()
    # _OAI_COMPAT_BASE_URLS dict present with exactly groq + openrouter
    assert "_OAI_COMPAT_BASE_URLS" in src
    assert "groq" in src and "openrouter" in src
    assert "api.groq.com/openai/v1" in src
    assert "openrouter.ai/api/v1" in src
    # _call_oai_compat handler present
    assert "_call_oai_compat" in src
    # _single_call routes through _OAI_COMPAT_BASE_URLS
    assert "provider in _OAI_COMPAT_BASE_URLS" in src
    # Owner-lock still there
    assert re.search(
        r"chain\s*=\s*\[s\s+for\s+s\s+in\s+chain\s+if\s+s\[0\]\s*!=\s*['\"]universal['\"]\]",
        src,
    ), "Owner-lock line missing"


# --- llm_chain module imports cleanly ---
def test_llm_chain_imports_and_dict_shape():
    import sys
    sys.path.insert(0, "/app/backend")
    import llm_chain  # noqa
    assert hasattr(llm_chain, "_OAI_COMPAT_BASE_URLS")
    assert set(llm_chain._OAI_COMPAT_BASE_URLS.keys()) == {"groq", "openrouter"}
    # TASK_CHAINS have groq+openrouter in each task
    for task in ("chat", "refine", "governance"):
        chain = llm_chain.TASK_CHAINS[task]
        provs = [c[1] for c in chain]
        assert "groq" in provs, f"{task} missing groq"
        assert "openrouter" in provs, f"{task} missing openrouter"
        # ollama should be last, groq/openrouter should be before ollama
        ollama_idx = provs.index("ollama")
        assert provs.index("groq") < ollama_idx
        assert provs.index("openrouter") < ollama_idx


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
