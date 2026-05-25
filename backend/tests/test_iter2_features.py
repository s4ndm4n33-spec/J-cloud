"""Iteration 2 backend tests: GitHub, Audit, Upload/Download, BYO Agents, .gauntletignore."""
from __future__ import annotations

import io
import os
import time

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://gauntlet-devspace.preview.emergentagent.com",
).rstrip("/")
TOKEN = "test_session_devspace_001"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**AUTH, "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update(AUTH)
    return s


@pytest.fixture(scope="session")
def project_id(session):
    r = session.post(
        f"{BASE_URL}/api/projects",
        json={"name": "TEST_iter2"},
        headers=JSON_HEADERS, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["project_id"]


# -------- GitHub --------
class TestGitHub:
    def setup_method(self):
        # Ensure no GH connection at start
        requests.delete(f"{BASE_URL}/api/github/auth", headers=AUTH, timeout=15)

    def test_auth_status_disconnected(self):
        r = requests.get(f"{BASE_URL}/api/github/auth", headers=AUTH, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("connected") is False

    def test_auth_invalid_token_400(self):
        r = requests.post(
            f"{BASE_URL}/api/github/auth",
            json={"token": "ghp_invalidtokenXXXXXXXXXXXXXXXXXXXX"},
            headers=JSON_HEADERS, timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_auth_short_token_400(self):
        r = requests.post(
            f"{BASE_URL}/api/github/auth",
            json={"token": "short"},
            headers=JSON_HEADERS, timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_repos_requires_connection(self):
        r = requests.get(f"{BASE_URL}/api/github/repos", headers=AUTH, timeout=15)
        assert r.status_code == 401, r.text

    def test_clone_requires_connection(self):
        r = requests.post(
            f"{BASE_URL}/api/github/clone",
            json={"full_name": "s4ndm4n33-spec/sovereign-shards"},
            headers=JSON_HEADERS, timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_auth_delete_returns_ok(self):
        r = requests.delete(f"{BASE_URL}/api/github/auth", headers=AUTH, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# -------- .gauntletignore seeding --------
class TestGauntletIgnore:
    def test_seeded_in_new_project(self, session, project_id):
        r = session.get(
            f"{BASE_URL}/api/projects/{project_id}/file",
            params={"path": ".gauntletignore"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert ".gauntletignore" in d.get("path", "") or len(d.get("content", "")) > 0
        # File must be non-empty
        assert len(d["content"]) > 0


# -------- Audit --------
class TestAudit:
    def test_audit_returns_100_point_score(self, session, project_id):
        r = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("score", "grade", "file_count", "breakdown", "recommendations", "destructive_findings"):
            assert k in d, f"audit missing key {k}: {d}"
        assert 0 <= d["score"] <= 100
        assert isinstance(d["breakdown"], (dict, list))
        assert isinstance(d["recommendations"], list)
        assert isinstance(d["destructive_findings"], list)
        assert d["file_count"] >= 1

    def test_audit_deterministic(self, session, project_id):
        a = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30).json()
        b = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30).json()
        assert a["score"] == b["score"], (a["score"], b["score"])
        assert a["file_count"] == b["file_count"]

    def test_recommendations_have_target_file(self, session, project_id):
        # Write a file with code-smells to provoke recommendations
        bad = (
            "def f(x):\n"
            "    out = []\n"
            "    for i in range(len(x)):\n"
            "        out.append(x[i])\n"
            "    return out\n"
        )
        session.post(
            f"{BASE_URL}/api/projects/{project_id}/file",
            json={"path": "TEST_bad.py", "content": bad},
            headers=JSON_HEADERS, timeout=15,
        )
        d = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30).json()
        recs = d["recommendations"]
        # Schema check: any code-level (five_masters) rec must include target_file
        fm_recs = [r for r in recs if r.get("category") == "five_masters"]
        for r in fm_recs:
            assert r.get("target_file"), r
        # Recommendations must not be empty
        assert recs, "no recommendations at all"


# -------- Upload / Download --------
class TestUploadDownload:
    def test_upload_then_audit_count_increments(self, session, project_id):
        before = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30).json()["file_count"]

        files = {"file": ("TEST_upload.py", io.BytesIO(b"x = 1\n"), "text/plain")}
        r = requests.post(
            f"{BASE_URL}/api/projects/{project_id}/upload",
            files=files, headers=AUTH, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["bytes"] == len(b"x = 1\n")

        after = session.get(f"{BASE_URL}/api/projects/{project_id}/audit", timeout=30).json()["file_count"]
        assert after >= before + 1, (before, after)

    def test_download_file_streams_content(self, session, project_id):
        # Ensure file exists
        session.post(
            f"{BASE_URL}/api/projects/{project_id}/file",
            json={"path": "TEST_dl.txt", "content": "dl-payload"},
            headers=JSON_HEADERS, timeout=15,
        )
        r = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/download",
            params={"path": "TEST_dl.txt"}, headers=AUTH, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.content == b"dl-payload"

    def test_download_zip_returns_archive(self, project_id):
        r = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/download_zip",
            headers=AUTH, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert len(r.content) > 100
        # ZIP magic bytes
        assert r.content[:2] == b"PK"


# -------- BYO Agents --------
class TestAgents:
    def test_list_initial_empty(self, session):
        # Best-effort cleanup of any pre-existing TEST_ agents
        existing = session.get(f"{BASE_URL}/api/agents", timeout=15).json().get("agents", [])
        for a in existing:
            if a.get("name", "").startswith("TEST_"):
                session.delete(f"{BASE_URL}/api/agents/{a['agent_id']}", timeout=15)
        r = session.get(f"{BASE_URL}/api/agents", timeout=15)
        assert r.status_code == 200
        names = [a.get("name", "") for a in r.json().get("agents", [])]
        assert not any(n.startswith("TEST_") for n in names)

    def test_create_without_name_400(self, session):
        r = session.post(
            f"{BASE_URL}/api/agents",
            json={"system_prompt": "x", "provider": "gemini", "model": "gemini-3-flash-preview"},
            headers=JSON_HEADERS, timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_create_then_delete(self, session):
        payload = {
            "name": "TEST_Agent_Z",
            "system_prompt": "You are Z.",
            "provider": "gemini",
            "model": "gemini-3-flash-preview",
        }
        r = session.post(
            f"{BASE_URL}/api/agents", json=payload,
            headers=JSON_HEADERS, timeout=15,
        )
        assert r.status_code == 200, r.text
        agent = r.json()
        assert agent["name"] == "TEST_Agent_Z"
        assert agent["provider"] == "gemini"
        agent_id = agent["agent_id"]

        # Verify via list
        listed = session.get(f"{BASE_URL}/api/agents", timeout=15).json()["agents"]
        assert any(a["agent_id"] == agent_id for a in listed)

        # Delete
        r = session.delete(f"{BASE_URL}/api/agents/{agent_id}", timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        listed_after = session.get(f"{BASE_URL}/api/agents", timeout=15).json()["agents"]
        assert not any(a["agent_id"] == agent_id for a in listed_after)
