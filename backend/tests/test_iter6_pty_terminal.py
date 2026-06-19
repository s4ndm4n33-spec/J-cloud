"""Iter6 — PTY WebSocket terminal + agent prompt addendum coverage."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
import requests
import websockets

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
BEARER = "test_session_devspace_001"
HEADERS = {"Authorization": f"Bearer {BEARER}"}

# strip ANSI escape sequences for substring matching
_ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


# --- helpers ---------------------------------------------------------------

def _get_project_id() -> str:
    r = requests.get(f"{BASE_URL}/api/projects", headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    projects = data if isinstance(data, list) else data.get("projects", [])
    if projects:
        return projects[0].get("project_id") or projects[0].get("id")
    cr = requests.post(
        f"{BASE_URL}/api/projects",
        headers=HEADERS,
        json={"name": "TEST_iter6_pty"},
        timeout=30,
    )
    cr.raise_for_status()
    body = cr.json()
    return body.get("project_id") or body["id"]


@pytest.fixture(scope="module")
def project_id() -> str:
    return _get_project_id()


async def _drain(ws, timeout: float = 0.8, max_loops: int = 40) -> str:
    """Read until silence; return concatenated decoded text."""
    out = []
    for _ in range(max_loops):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            break
        if isinstance(msg, (bytes, bytearray)):
            out.append(bytes(msg).decode("utf-8", errors="replace"))
        else:
            out.append(str(msg))
    return "".join(out)


async def _send_cmd(ws, line: str) -> None:
    await ws.send(json.dumps({"type": "input", "data": line + "\r"}))


# --- AUTH ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_rejects_without_auth(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}"
    # Server may either (a) reject the upgrade with HTTP 401/403, or
    # (b) accept then immediately close with code 4401. Accept both.
    try:
        async with websockets.connect(url, open_timeout=8) as ws:
            with pytest.raises((
                websockets.exceptions.ConnectionClosed,
                asyncio.TimeoutError,
            )):
                # Reading should either fail with close=4401 or never deliver data
                await asyncio.wait_for(ws.recv(), timeout=3.0)
            # If we got here via ConnectionClosed, verify the code
            assert ws.close_code in (4401, 1006, 1000), \
                f"unexpected close code {ws.close_code}"
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code in (401, 403, 404), \
            f"unexpected status {e.response.status_code}"


@pytest.mark.asyncio
async def test_ws_accepts_with_query_token(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        banner = await _drain(ws, timeout=1.5)
        assert "Gauntlet DevSpace" in _strip(banner)
        assert "interactive shell" in _strip(banner)
        # PS1 colored prompt arrives — look for the marker
        assert "J@sovereign" in _strip(banner)


# --- PERSISTENT STATE ------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_persistent_env(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "export FOO=bar")
        await _drain(ws, timeout=0.6)
        await _send_cmd(ws, "echo FOO=$FOO")
        out = _strip(await _drain(ws, timeout=1.2))
        assert "FOO=bar" in out, f"got: {out!r}"


@pytest.mark.asyncio
async def test_ws_persistent_cd(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "pwd")
        first = _strip(await _drain(ws, timeout=1.0))
        await _send_cmd(ws, "cd ..")
        await _drain(ws, timeout=0.6)
        await _send_cmd(ws, "pwd")
        second = _strip(await _drain(ws, timeout=1.0))
        # Pick only lines that are pure absolute paths (no PS1 noise)
        path_re = re.compile(r"^/[A-Za-z0-9_./-]+$")
        first_paths = [ln.strip() for ln in first.splitlines() if path_re.match(ln.strip())]
        second_paths = [ln.strip() for ln in second.splitlines() if path_re.match(ln.strip())]
        assert first_paths, f"no pwd in: {first!r}"
        assert second_paths, f"no pwd in: {second!r}"
        assert first_paths[-1] != second_paths[-1], \
            f"cd did not change pwd: {first_paths[-1]!r} == {second_paths[-1]!r}"
        assert second_paths[-1] == str(Path(first_paths[-1]).parent)


# --- DESTRUCTIVE TRAP ------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_destructive_rm_refused(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "rm -rf /")
        out = _strip(await _drain(ws, timeout=1.5))
        assert "INTEGRITY HALT" in out
        assert "destructive command refused" in out
        # Sanity — also test a canary still works (rm did NOT execute)
        await _send_cmd(ws, "ls /etc >/dev/null && echo OK_ETC")
        out2 = _strip(await _drain(ws, timeout=1.5))
        assert "OK_ETC" in out2


@pytest.mark.asyncio
async def test_ws_destructive_mkfs_refused(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "mkfs.ext4 /dev/sda")
        out = _strip(await _drain(ws, timeout=1.5))
        assert "INTEGRITY HALT" in out
        assert "block-device write refused" in out


# --- REPL ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_python_repl(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "python3")
        banner = _strip(await _drain(ws, timeout=2.5))
        assert "Python 3." in banner, f"no python banner: {banner!r}"
        await _send_cmd(ws, "print(7*6)")
        out = _strip(await _drain(ws, timeout=1.5))
        assert "42" in out
        await _send_cmd(ws, "exit()")
        await _drain(ws, timeout=1.0)
        # Back to bash — echo confirms
        await _send_cmd(ws, "echo BACK_TO_BASH")
        bash_out = _strip(await _drain(ws, timeout=1.2))
        assert "BACK_TO_BASH" in bash_out


# --- RESIZE ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_resize(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 30}))
        await asyncio.sleep(0.3)
        await _send_cmd(ws, "stty size")
        out = _strip(await _drain(ws, timeout=1.5))
        # stty prints "rows cols"
        assert "30 120" in out, f"stty size mismatch: {out!r}"


# --- J-HELP ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_j_help(project_id):
    url = f"{WS_URL}/api/terminal/ws?project_id={project_id}&token={BEARER}"
    async with websockets.connect(url) as ws:
        await _drain(ws, timeout=1.2)
        await _send_cmd(ws, "j-help")
        raw = await _drain(ws, timeout=2.0)
        out = _strip(raw)
        # Multi-section
        assert "GAUNTLET DEVSPACE TERMINAL" in out
        assert "Scope" in out and "Available" in out and "Persistence" in out
        # ANSI cyan present in RAW (not stripped)
        assert "\x1b[36m" in raw, "expected cyan ANSI escape in j-help"
        # No spurious INTEGRITY HALT triggered by internal commands
        assert "INTEGRITY HALT" not in out


# --- HTTP /api/terminal/exec timeout regression ---------------------------

def test_http_exec_timeout_is_300(tmp_path=None):
    """Verify source: 300s timeout, error message updated."""
    src = Path("/app/backend/server.py").read_text(encoding="utf-8")
    assert "timeout=300" in src, "300s timeout not present in /api/terminal/exec"
    assert "Timeout (300s)" in src, "updated timeout error message missing"
    # 30s artifact should be gone from exec
    assert "timeout=30)" not in src, "leftover 30s timeout still in source"


def test_http_exec_still_authed_and_blocks_destructive():
    """Existing destructive-pattern + override flow stays functional."""
    pid = _get_project_id()
    r = requests.post(
        f"{BASE_URL}/api/terminal/exec",
        headers=HEADERS,
        json={"project_id": pid, "command": "rm -rf /"},
        timeout=15,
    )
    # Existing flow returns 423 (HardBlock) for destructive — preserved
    assert r.status_code in (423, 400), f"unexpected status {r.status_code}: {r.text[:200]}"


def test_http_exec_benign_runs():
    pid = _get_project_id()
    r = requests.post(
        f"{BASE_URL}/api/terminal/exec",
        headers=HEADERS,
        json={"project_id": pid, "command": "echo hello_iter6"},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert "hello_iter6" in (body.get("stdout") or "")


# --- AGENT PROMPT ADDENDUM -------------------------------------------------

def test_terminal_reference_file_exists():
    p = Path("/app/backend/core/terminal_reference.md")
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "TERMINAL REFERENCE" in content
    assert "run_command" in content
    assert "rm -rf /" in content


def test_agent_prompt_includes_terminal_reference():
    p = Path("/app/backend/core/agent_prompt.py")
    src = p.read_text(encoding="utf-8")
    assert "terminal_reference.md" in src
    assert "_TERMINAL_REF" in src
    # Compose and check effective prompt
    import importlib
    import sys
    sys.path.insert(0, "/app/backend")
    mod = importlib.import_module("core.agent_prompt")
    assert "TERMINAL REFERENCE" in mod.AGENT_PROMPT
    assert "destructive" in mod.AGENT_PROMPT.lower()
