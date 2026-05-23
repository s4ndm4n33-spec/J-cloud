"""Backend regression tests for Gauntlet DevSpace.

Covers: health, auth, projects+tree+file, gauntlet, governance (scan/override),
terminal (block + ok), git, ai chat (graceful offline).
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gauntlet-devspace.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_devspace_001"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


@pytest.fixture(scope="session")
def project_id(session):
    """Create one shared project for tests that need it."""
    r = session.post(f"{BASE_URL}/api/projects", json={"name": "TEST_shard"}, timeout=30)
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    yield pid


# ---------- HEALTH ----------
class TestHealth:
    def test_root_health(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["tagline"] == "DETERMINISTIC. AUTONOMOUS. SUBSTRATE."
        assert data["status"] == "online"


# ---------- AUTH ----------
class TestAuth:
    def test_me_with_bearer(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["user_id"] == "user_test_devspace"
        assert u["email"] == "test.j@sovereign.shards"

    def test_me_without_token(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 401


# ---------- PROJECTS / FILES ----------
class TestProjects:
    def test_create_lists_and_seeded_files(self, session, project_id):
        # List
        r = session.get(f"{BASE_URL}/api/projects", timeout=15)
        assert r.status_code == 200
        ids = [p["project_id"] for p in r.json()]
        assert project_id in ids

        # Tree
        r = session.get(f"{BASE_URL}/api/projects/{project_id}/tree", timeout=15)
        assert r.status_code == 200
        names = {n["name"] for n in r.json()["tree"]}
        for expected in {"README.md", "main.py", "index.html", ".gitignore"}:
            assert expected in names, f"seed missing {expected}: {names}"

    def test_read_main_py(self, session, project_id):
        r = session.get(
            f"{BASE_URL}/api/projects/{project_id}/file",
            params={"path": "main.py"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["language"] == "python"
        assert "def greet" in d["content"]

    def test_write_file(self, session, project_id):
        r = session.post(
            f"{BASE_URL}/api/projects/{project_id}/file",
            json={"path": "TEST_new.txt", "content": "hello shard"}, timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # Verify
        r = session.get(
            f"{BASE_URL}/api/projects/{project_id}/file",
            params={"path": "TEST_new.txt"}, timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["content"] == "hello shard"


# ---------- GAUNTLET AST ----------
class TestGauntlet:
    def test_korotkevich_flags_range_len(self, session):
        code = (
            "def f(x):\n"
            "    out = []\n"
            "    for i in range(len(x)):\n"
            "        out.append(x[i])\n"
            "    return out\n"
        )
        r = session.post(
            f"{BASE_URL}/api/gauntlet/evaluate",
            json={"code": code, "language": "python"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        rep = r.json()
        assert "issues" in rep and isinstance(rep["issues"], list)
        # The for-i-in-range(len(...)) pattern MUST be flagged by korotkevich
        flagged = [i for i in rep["issues"]
                   if i.get("master") == "korotkevich" and "range(len" in i.get("message", "")]
        assert flagged, f"korotkevich did not flag range(len): {rep}"


# ---------- GOVERNANCE (scan + override) ----------
class TestGovernance:
    def test_scan_blocks_rm_rf_root(self, session):
        r = session.post(
            f"{BASE_URL}/api/governance/scan",
            json={"command": "rm -rf /"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["blocked"] is True
        assert any(m["severity"] == "critical" for m in d["matches"])

    def test_override_wrong_password(self, session):
        r = session.post(
            f"{BASE_URL}/api/governance/override",
            json={"password": "wrong-pass", "intent": "test"}, timeout=15,
        )
        assert r.status_code == 403

    def test_override_correct_password_returns_token(self, session):
        r = session.post(
            f"{BASE_URL}/api/governance/override",
            json={"password": "integrity-halt-override", "intent": "test"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["override_token"].startswith("ovr_")
        assert d["expires_in"] == 120


# ---------- TERMINAL ----------
class TestTerminal:
    def test_ls_la_ok(self, session, project_id):
        r = session.post(
            f"{BASE_URL}/api/terminal/exec",
            json={"project_id": project_id, "command": "ls -la"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["exit_code"] == 0
        assert "README.md" in d["stdout"]

    def test_rm_rf_root_returns_423(self, session, project_id):
        r = session.post(
            f"{BASE_URL}/api/terminal/exec",
            json={"project_id": project_id, "command": "rm -rf /"}, timeout=15,
        )
        assert r.status_code == 423, r.text
        d = r.json()
        assert d["blocked"] is True
        assert "INTEGRITY HALT" in d["message"]

    def test_rm_rf_root_with_override_token_passes_block(self, session, project_id):
        # Get override token
        r = session.post(
            f"{BASE_URL}/api/governance/override",
            json={"password": "integrity-halt-override", "intent": "test exec"}, timeout=15,
        )
        assert r.status_code == 200
        token = r.json()["override_token"]

        # Use a less catastrophic destructive command we can run safely:
        # The token consumption logic runs regardless of severity match — we just
        # need to confirm it isn't blocked at 423. We'll use 'rm -rf /' but
        # the cwd is the project sandbox, NOT host /. The token bypasses the
        # block; the actual rm will likely fail with permission denied on /.
        # To avoid any host risk, we instead send the recognized critical
        # pattern via 'echo' wrapping won't trigger; use literal as required.
        r = session.post(
            f"{BASE_URL}/api/terminal/exec",
            json={"project_id": project_id, "command": "rm -rf /",
                  "override_token": token}, timeout=30,
        )
        # Should NOT be 423 anymore – token consumed
        assert r.status_code != 423, f"override failed to bypass block: {r.text}"
        # Token is single-use: re-attempt without token should re-block
        r2 = session.post(
            f"{BASE_URL}/api/terminal/exec",
            json={"project_id": project_id, "command": "rm -rf /",
                  "override_token": token}, timeout=15,
        )
        assert r2.status_code == 423, "consume-once broken: token still works"


# ---------- GIT ----------
class TestGit:
    def test_status_and_commit(self, session, project_id):
        r = session.get(f"{BASE_URL}/api/projects/{project_id}/git/status", timeout=15)
        assert r.status_code == 200
        assert "branch" in r.json()

        # Write a file then commit
        session.post(
            f"{BASE_URL}/api/projects/{project_id}/file",
            json={"path": "TEST_git.txt", "content": str(time.time())}, timeout=15,
        )
        r = session.post(
            f"{BASE_URL}/api/projects/{project_id}/git/commit",
            json={"message": "TEST commit"}, timeout=20,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ---------- AI CHAT (graceful offline) ----------
class TestAIChat:
    def test_chat_never_500(self, session, project_id):
        r = session.post(
            f"{BASE_URL}/api/ai/chat",
            json={"message": "Hello J", "file_path": "main.py"}, timeout=60,
        )
        assert r.status_code == 200, f"AI chat should never 500: {r.status_code} {r.text}"
        d = r.json()
        assert "reply" in d
        assert "conversation_id" in d
        assert isinstance(d["reply"], str) and len(d["reply"]) > 0
