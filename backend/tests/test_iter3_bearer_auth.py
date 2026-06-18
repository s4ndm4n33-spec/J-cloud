"""Iter3 — Bearer-token fallback for mobile OAuth.

Validates that protected endpoints accept BOTH a `session_token` cookie and an
`Authorization: Bearer <token>` header, that auth/session returns the token in
the JSON body, and that logout still works (even though current impl only
deletes by cookie, it still returns 200 when called with just the Bearer hdr).
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOKEN = "test_session_devspace_001"
EXPECTED_USER_ID = "user_test_devspace"
EXPECTED_EMAIL = "test.j@sovereign.shards"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# --- /auth/me Bearer + cookie + unauth ---

class TestAuthMe:
    def test_me_unauthenticated_returns_401(self, s):
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401, r.text

    def test_me_with_bearer_token_returns_200(self, s):
        r = s.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == EXPECTED_USER_ID
        assert data["email"] == EXPECTED_EMAIL
        # MongoDB ObjectId never leaks
        assert "_id" not in data

    def test_me_with_session_cookie_returns_200(self, s):
        r = s.get(
            f"{BASE_URL}/api/auth/me",
            cookies={"session_token": TOKEN},
        )
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == EXPECTED_USER_ID

    def test_me_with_bogus_bearer_returns_401(self, s):
        r = s.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": "Bearer not_a_real_token_xxx"},
        )
        assert r.status_code == 401

    def test_me_with_malformed_authorization_header_returns_401(self, s):
        # Missing "Bearer " prefix should be ignored, falling through to 401.
        r = s.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": TOKEN},
        )
        assert r.status_code == 401

    def test_cookie_takes_precedence_over_bearer_when_both_present(self, s):
        # Cookie is valid, Bearer is junk → should still 200 (cookie path used).
        r = s.get(
            f"{BASE_URL}/api/auth/me",
            cookies={"session_token": TOKEN},
            headers={"Authorization": "Bearer junk"},
        )
        assert r.status_code == 200


# --- /auth/session contract: must return session_token in JSON body ---

class TestAuthSessionContract:
    def test_missing_session_id_returns_400(self, s):
        r = s.post(f"{BASE_URL}/api/auth/session", json={})
        assert r.status_code == 400

    def test_bad_session_id_returns_401_from_emergent(self, s):
        # Emergent rejects garbage → backend forwards as 401.
        r = s.post(
            f"{BASE_URL}/api/auth/session",
            json={"session_id": "definitely_not_a_real_emergent_session_id"},
        )
        assert r.status_code == 401


# --- /auth/logout ---

class TestAuthLogout:
    def test_logout_with_bearer_only_returns_200(self, s):
        # NOTE: backend implementation currently deletes the user_sessions row
        # by cookie value only, so a Bearer-only logout still returns 200 but
        # does NOT invalidate the token. We assert the 200 contract; the gap
        # is documented in the iter3 report.
        r = s.post(
            f"{BASE_URL}/api/auth/logout",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_logout_no_auth_still_returns_200(self, s):
        r = s.post(f"{BASE_URL}/api/auth/logout")
        assert r.status_code == 200


# --- Protected endpoints accept Bearer ---

class TestProtectedEndpointsBearer:
    def test_projects_list_with_bearer(self, s):
        r = s.get(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_projects_list_unauth_returns_401(self, s):
        r = s.get(f"{BASE_URL}/api/projects")
        assert r.status_code == 401

    def test_ai_chain_with_bearer(self, s):
        r = s.get(
            f"{BASE_URL}/api/ai/chain",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "chains" in body
        assert "chat" in body["chains"]

    def test_settings_keys_with_bearer(self, s):
        r = s.get(
            f"{BASE_URL}/api/settings/keys",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200
        assert "providers" in r.json()
