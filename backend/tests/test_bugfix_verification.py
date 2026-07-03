"""Bug fix verification: CIG HTML acceptance + regression sweep.

BUG1: Code Integrity Gateway must accept valid HTML files.
BUG2: (frontend, tested via playwright) Mobile Send button now calls send().

This module verifies:
  - CIG unit-level: valid HTML passes, truncation markers still rejected,
    Python cliff-ending still rejected.
  - Endpoints: /api/, /api/projects list, /api/projects/{id}/tree, file write.
  - AI chat receives the typed text (not a click-event string).
"""
from __future__ import annotations

import os
import sys
import pathlib

import pytest
import requests

# Make backend package importable for the direct CIG unit tests
ROOT = pathlib.Path("/app/backend").resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.code_integrity import validate  # noqa: E402

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://gauntlet-devspace.preview.emergentagent.com",
).rstrip("/")
TOKEN = "test_session_devspace_001"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

VALID_HTML = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head><meta charset=\"utf-8\">"
    "<title>Nissan Versa Door Lock</title></head>\n<body>\n"
    "<svg viewBox=\"0 0 100 100\" xmlns=\"http://www.w3.org/2000/svg\">"
    "<circle cx=\"50\" cy=\"50\" r=\"40\"/></svg>\n"
    "</body>\n</html>\n"
)


# ---------- CIG unit-level ----------
class TestCIG:
    def test_valid_html_with_svg_passes(self):
        r = validate("diagram.html", VALID_HTML)
        assert r.ok, f"Valid HTML rejected: {r.error} @ line {r.line}"
        assert r.language == "html"

    def test_html_truncation_marker_rejected(self):
        bad = (
            "<!DOCTYPE html>\n<html><body>\n"
            "<!-- rest of file unchanged -->\n"
            "</body></html>\n"
        )
        r = validate("bad.html", bad)
        assert not r.ok
        assert "Truncation" in r.error or "truncation" in r.error.lower()

    def test_python_cliff_still_rejected(self):
        r = validate("bad.py", "def foo():\n    return 1 +\n")
        assert not r.ok


# ---------- Endpoint regression sweep ----------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


@pytest.fixture(scope="module")
def project_id(session):
    r = session.post(
        f"{BASE_URL}/api/projects",
        json={"name": "TEST_bugfix_verify"},
        timeout=30,
    )
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text[:200]}"
    pid = r.json()["project_id"]
    yield pid
    try:
        session.delete(f"{BASE_URL}/api/projects/{pid}", timeout=15)
    except Exception:
        pass


class TestRegression:
    def test_health(self, session):
        r = session.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200

    def test_projects_list(self, session):
        r = session.get(f"{BASE_URL}/api/projects", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_project_tree(self, session, project_id):
        r = session.get(
            f"{BASE_URL}/api/projects/{project_id}/tree", timeout=15,
        )
        assert r.status_code == 200
        assert "tree" in r.json()

    def test_write_valid_html_via_endpoint(self, session, project_id):
        """POST /api/projects/{id}/file with valid HTML must succeed."""
        r = session.post(
            f"{BASE_URL}/api/projects/{project_id}/file",
            json={"path": "diagram.html", "content": VALID_HTML},
            timeout=30,
        )
        assert r.status_code == 200, f"HTML write failed: {r.status_code} {r.text[:300]}"
        # Read back to verify persistence
        r2 = session.get(
            f"{BASE_URL}/api/projects/{project_id}/file",
            params={"path": "diagram.html"},
            timeout=15,
        )
        assert r2.status_code == 200
        assert "<!DOCTYPE html>" in r2.json()["content"]


class TestAIChatTextIntegrity:
    """Ensure the AI chat endpoint accepts a plain user message string
    (not a synthetic React click-event stringified as '[object Object]').
    We can't cheaply invoke the LLM chain reliably in test env; we assert
    the request is accepted and the persisted message.role=user content
    equals what we sent.
    """

    def test_chat_persists_typed_text(self, session):
        typed = "TEST_bugfix hello J please respond briefly"
        r = session.post(
            f"{BASE_URL}/api/ai/chat",
            json={"message": typed},
            timeout=120,
        )
        assert r.status_code == 200, f"ai/chat failed: {r.status_code} {r.text[:300]}"
        conv_id = r.json()["conversation_id"]
        h = session.get(
            f"{BASE_URL}/api/ai/chat/history",
            params={"conversation_id": conv_id},
            timeout=15,
        )
        assert h.status_code == 200
        msgs = h.json()["messages"]
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert user_msgs, "no user message persisted"
        assert user_msgs[0]["content"] == typed, (
            f"content mismatch — got: {user_msgs[0]['content'][:120]!r}"
        )
        assert "[object Object]" not in user_msgs[0]["content"]
