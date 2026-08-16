#!/usr/bin/env python3
"""Sovereign Shard offline acceptance smoke test.

Validates that the backend boots in portable mode, core endpoints respond,
local auth works, project CRUD works, and cloud adapters are disabled —
all without any network access.

Usage:
    python3 sovereign/tests/smoke_test.py [--shard-dir <path>] [--timeout <sec>]

Exit codes:
    0  PASS — all smoke checks passed
    1  FAIL — one or more checks failed
    2  ERROR — could not run (missing dependencies, import failure)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

PASS = "\033[0;32mPASS\033[0m"
FAIL = "\033[0;31mFAIL\033[0m"
INFO = "\033[0;36mINFO\033[0m"
WARN = "\033[0;33mWARN\033[0m"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    status = PASS if ok else FAIL
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def http_get(url: str, timeout: int = 5) -> tuple[int, dict | None]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def http_post(url: str, data: dict, timeout: int = 5) -> tuple[int, dict | None]:
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(resp_body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


def wait_for_backend(port: int, timeout_sec: int) -> bool:
    url = f"http://127.0.0.1:{port}/api/"
    for _ in range(timeout_sec):
        code, _ = http_get(url, timeout=2)
        if code == 200:
            return True
        time.sleep(1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Sovereign shard smoke test")
    parser.add_argument("--shard-dir", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    shard_dir: Path = args.shard_dir
    backend_dir = shard_dir / "backend"

    if not backend_dir.exists():
        print(f"{FAIL}: Backend directory not found at {backend_dir}")
        return 2

    # Set portable environment
    env = os.environ.copy()
    env["J_CLOUD_PROFILE"] = "portable"
    env["J_CLOUD_ROOT"] = str(shard_dir)
    env["LOCAL_LLM_BASE_URL"] = "http://127.0.0.1:18099/v1"
    env["LOCAL_LLM_MODEL"] = "smoke-test-model"
    env["LOCAL_AUTH"] = "1"
    env["WORKSPACE_ROOT"] = str(shard_dir / "workspace")
    env["CORS_ORIGINS"] = "*"
    # Ensure no cloud credentials leak in
    for key in ["EMERGENT_LLM_KEY", "MONGO_URL", "TAVILY_API_KEY",
                "RESEND_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
                "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
        env.pop(key, None)

    print(f"\n{INFO} Sovereign Shard Smoke Test")
    print(f"{INFO} Shard dir: {shard_dir}")
    print(f"{INFO} Backend port: {args.port}")
    print()

    # Start backend
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(args.port),
         "--app-dir", str(backend_dir)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for backend to be ready
        if not wait_for_backend(args.port, args.timeout):
            record("backend boots", False, "did not respond within timeout")
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            if stderr:
                print(f"\n{FAIL} Backend stderr:\n{stderr[:2000]}")
            return 1
        record("backend boots", True)

        # Check root endpoint
        code, body = http_get(f"http://127.0.0.1:{args.port}/api/")
        record("root endpoint /api/", code == 200 and body is not None and body.get("status") == "online",
               f"status={code}")

        # Check sovereign status
        code, body = http_get(f"http://127.0.0.1:{args.port}/api/sovereign/status")
        record("sovereign status endpoint", code == 200,
               f"status={code}")
        if body:
            record("  profile is portable", body.get("profile") == "portable",
                   f"profile={body.get('profile')}")
            record("  database is sqlite", body.get("database") == "sqlite",
                   f"database={body.get('database')}")
            record("  authentication is local", body.get("authentication") == "local",
                   f"authentication={body.get('authentication')}")
            record("  workspace ready", body.get("workspace") == "ready",
                   f"workspace={body.get('workspace')}")
            record("  local_llm unavailable (no model server)", body.get("local_llm") == "unavailable",
                   f"local_llm={body.get('local_llm')}")
            cloud = body.get("cloud_adapters", {})
            all_disabled = all(not v.get("enabled") for v in cloud.values()) if cloud else True
            record("  all cloud adapters disabled", all_disabled,
                   f"adapters={list(cloud.keys()) if cloud else 'none'}")

        # Test local auth init
        code, body = http_post(
            f"http://127.0.0.1:{args.port}/api/auth/local/init",
            {"email": "smoke@local.shard", "name": "Smoke Test", "password": "test123"},
        )
        record("local auth init", code == 200 and body is not None and "session_token" in (body or {}),
               f"status={code}")
        token = (body or {}).get("session_token", "")

        # Test local auth login
        code, body = http_post(
            f"http://127.0.0.1:{args.port}/api/auth/local/login",
            {"email": "smoke@local.shard", "password": "test123"},
        )
        record("local auth login", code == 200 and body is not None and "session_token" in (body or {}),
               f"status={code}")

        # Test /auth/me with token
        me_url = f"http://127.0.0.1:{args.port}/api/auth/me"
        try:
            req = urllib.request.Request(me_url)
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                me_body = json.loads(resp.read().decode("utf-8"))
            record("auth/me with token", resp.status == 200 and me_body.get("email") == "smoke@local.shard",
                   f"email={me_body.get('email')}")
        except Exception as e:
            record("auth/me with token", False, str(e))

        # Test project creation
        code, body = http_post(
            f"http://127.0.0.1:{args.port}/api/projects",
            {"name": "Smoke Project"},
        )
        record("project creation", code == 200 and body is not None and "project_id" in (body or {}),
               f"status={code}")
        project_id = (body or {}).get("project_id", "")

        # Test project list
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/projects")
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                projects = json.loads(resp.read().decode("utf-8"))
            record("project list", resp.status == 200 and isinstance(projects, list) and len(projects) >= 1,
                   f"count={len(projects) if isinstance(projects, list) else 'n/a'}")
        except Exception as e:
            record("project list", False, str(e))

        # Test file write
        if project_id:
            code, body = http_post(
                f"http://127.0.0.1:{args.port}/api/projects/{project_id}/file",
                {"path": "test.py", "content": "print('smoke test')\n"},
            )
            record("file write", code == 200, f"status={code}")

            # Test file read
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{args.port}/api/projects/{project_id}/file?path=test.py"
                )
                req.add_header("Authorization", f"Bearer {token}")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    file_body = json.loads(resp.read().decode("utf-8"))
                record("file read", resp.status == 200 and "print('smoke test')" in (file_body.get("content", "") if file_body else ""),
                       f"status={resp.status}")
            except Exception as e:
                record("file read", False, str(e))

        # Test cloud adapter rejection (GitHub)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{args.port}/api/github/repos",
                headers={"Authorization": f"Bearer {token}"},
            )
            urllib.request.urlopen(req, timeout=5)
            record("github adapter disabled (503)", False, "expected 503")
        except urllib.error.HTTPError as e:
            record("github adapter disabled (503)", e.code == 503, f"status={e.code}")
        except Exception:
            record("github adapter disabled (503)", False, "connection error")

        # Test voice adapter rejection
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{args.port}/api/voice/speak",
                data=json.dumps({"text": "test"}).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            record("voice adapter disabled (503)", False, "expected 503")
        except urllib.error.HTTPError as e:
            record("voice adapter disabled (503)", e.code == 503, f"status={e.code}")
        except Exception:
            record("voice adapter disabled (503)", False, "connection error")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    print()
    print(f"{'=' * 50}")
    print(f"  SMOKE TEST RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 50}")

    if failed > 0:
        print(f"\n{FAIL} Failed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
        return 1

    print(f"\n{PASS} All smoke checks passed. Shard is operational in portable mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
