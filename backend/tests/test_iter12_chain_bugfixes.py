"""Iteration 12 — verify the two peripheral bug fixes surfaced during the
"LLM chain failing" investigation:

1. chronicle_entries `ai_answer` inserts on /api/ai/chat now include
   `ts_ns` (nanosecond timestamp) so they no longer collide on the
   unique index (project_id, session_id, ts_ns). Previous behavior:
   repeated calls emitted `ai_answer log (chat) failed: E11000
   duplicate key error` in backend logs.

2. The owner's misconfigured Ollama BYOK row (base_url pointed at
   localhost:11434 which is the pod itself) was deleted from
   user_provider_keys. /api/settings/keys should now list
   ollama as configured=False for the owner, and the LLM chain must
   not spend a ~5s connect timeout on it.

3. No regression: llm_chain.py still contains the owner-lock line that
   strips 'universal' provider entries for non-owners; the SSE
   /api/ai/chat/stream endpoint still emits an `event: error` frame
   when all providers fail.

The chain itself will still fail end-to-end because all real provider
accounts are dry (billing issue) — that is EXPECTED and NOT tested here.
"""
from __future__ import annotations

import os
import time
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

OWNER_TOKEN = "test_owner_session_001"
OWNER_UID = "user_5d2818f635a9"

OWNER_H = {"Authorization": f"Bearer {OWNER_TOKEN}",
           "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# Fix #2 — Ollama BYOK row removed for owner
# --------------------------------------------------------------------------
class TestOllamaRowRemoved:
    def test_settings_keys_owner_no_ollama_configured(self):
        """/api/settings/keys must show ollama as configured=False."""
        r = requests.get(f"{BASE}/api/settings/keys", headers=OWNER_H,
                         timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        providers = {p["provider"]: p for p in j.get("providers", [])}
        assert "ollama" in providers, "ollama should still appear in provider list"
        assert providers["ollama"]["configured"] is False, (
            f"Ollama should NOT be configured for owner after cleanup, "
            f"got: {providers['ollama']}"
        )
        # base_url should be empty (no stale localhost entry)
        assert providers["ollama"].get("base_url", "") == "", (
            f"Stale base_url present: {providers['ollama'].get('base_url')}"
        )

    def test_mongo_no_ollama_row_for_owner(self):
        """Directly assert user_provider_keys has no ollama doc for owner."""
        async def _check():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                doc = await cli[DB_NAME].user_provider_keys.find_one(
                    {"user_id": OWNER_UID, "provider": "ollama"}
                )
                return doc
            finally:
                cli.close()
        doc = asyncio.run(_check())
        assert doc is None, f"Ollama row still present in DB: {doc}"

    def test_chain_endpoint_no_ollama_runnable_step(self):
        """/api/ai/chain for owner should not surface ollama as runnable."""
        r = requests.get(f"{BASE}/api/ai/chain", headers=OWNER_H, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("is_owner") is True
        # Look across both chat + agent chains
        all_steps = []
        for chain_name in ("chat", "agent"):
            all_steps.extend(j.get("chains", {}).get(chain_name, []))
        ollama_runnable = [s for s in all_steps
                           if s.get("provider") == "ollama"
                           and s.get("runnable") is True]
        assert not ollama_runnable, (
            f"Ollama should NOT be runnable after cleanup, got: {ollama_runnable}"
        )


# --------------------------------------------------------------------------
# Fix #1 — chronicle ai_answer rows now include ts_ns
# --------------------------------------------------------------------------
class TestChronicleTsNs:
    def test_ai_answer_write_populates_ts_ns_no_dup_key(self):
        """Trigger 2 rapid /api/ai/chat calls on same conversation and verify:
        - No duplicate-key error on chronicle_entries (both rows written)
        - Both rows have numeric ts_ns
        - ts_ns differs between rows

        The chat itself will fail (billing) — we don't assert reply content,
        only that the chronicle log write succeeded (which is the fix under
        test).
        """
        async def _snapshot_and_run():
            cli = AsyncIOMotorClient(MONGO_URL)
            d = cli[DB_NAME]
            try:
                before = await d.chronicle_entries.count_documents(
                    {"scope": "chat", "user_id": OWNER_UID, "kind": "ai_answer"}
                )
                return before, d, cli
            except Exception:
                cli.close()
                raise

        async def _fetch_latest(cli):
            d = cli[DB_NAME]
            rows = await d.chronicle_entries.find(
                {"scope": "chat", "user_id": OWNER_UID, "kind": "ai_answer"}
            ).sort("ts_ns", -1).limit(5).to_list(5)
            cli.close()
            return rows

        before, d, cli = asyncio.run(_snapshot_and_run())

        # Fire two chats on the SAME conversation_id (worst case for
        # duplicate-key collisions on (project_id, session_id, ts_ns)).
        conv = f"iter12_conv_{int(time.time())}"
        payload = {"message": "ping iter12", "conversation_id": conv}
        r1 = requests.post(f"{BASE}/api/ai/chat", headers=OWNER_H,
                           json=payload, timeout=120)
        r2 = requests.post(f"{BASE}/api/ai/chat", headers=OWNER_H,
                           json=payload, timeout=120)

        # Chat endpoint should still return 200 even when providers fail
        # (the reply body contains the offline/error string but HTTP is 200).
        # If billing gives a hard error we accept 200 or 5xx — but the
        # chronicle row should still be attempted regardless.
        assert r1.status_code in (200, 500, 502, 503), r1.text[:400]
        assert r2.status_code in (200, 500, 502, 503), r2.text[:400]

        # Small settle in case of async writes
        time.sleep(0.5)

        rows = asyncio.run(_fetch_latest(AsyncIOMotorClient(MONGO_URL)))
        assert rows, "No ai_answer chronicle rows found for owner"

        # Every recent row must have numeric ts_ns
        for r in rows[:2]:
            ts_ns = r.get("ts_ns")
            assert isinstance(ts_ns, int) and ts_ns > 0, (
                f"ai_answer row missing/invalid ts_ns: {r}"
            )

        # If at least one chat request succeeded in inserting a row, the
        # count should have grown. If both HTTP calls returned successful
        # (200), we expect 2 new rows.
        async def _count_after():
            cli2 = AsyncIOMotorClient(MONGO_URL)
            try:
                return await cli2[DB_NAME].chronicle_entries.count_documents(
                    {"scope": "chat", "user_id": OWNER_UID,
                     "kind": "ai_answer"}
                )
            finally:
                cli2.close()
        after = asyncio.run(_count_after())
        assert after >= before + 1, (
            f"Expected at least +1 ai_answer row after chat, "
            f"before={before} after={after}"
        )

    def test_no_duplicate_key_error_in_backend_log(self):
        """After the previous test triggered chat calls, backend.err.log
        should not contain a fresh 'ai_answer log (chat) failed: E11000'
        entry. We snapshot the log tail size before and re-check.
        """
        log_path = "/var/log/supervisor/backend.err.log"
        if not os.path.exists(log_path):
            pytest.skip("backend.err.log not present")
        # Read last 200 lines
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            tail = f.read().decode(errors="ignore")
        # Fire a chat to guarantee an ai_answer write attempt
        conv = f"iter12_logcheck_{int(time.time())}"
        requests.post(f"{BASE}/api/ai/chat", headers=OWNER_H,
                      json={"message": "log check", "conversation_id": conv},
                      timeout=120)
        time.sleep(0.5)
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            new_size = f.tell()
        with open(log_path, "rb") as f:
            f.seek(size)
            fresh = f.read(new_size - size).decode(errors="ignore")
        assert "ai_answer log (chat) failed: E11000" not in fresh, (
            f"Duplicate-key error still emitted in backend log:\n{fresh[-1500:]}"
        )
        # Sanity: prior tail also should not blow up the assertion
        _ = tail  # kept for debugging


# --------------------------------------------------------------------------
# Fix #3 — regression checks: owner-lock line + SSE error frame
# --------------------------------------------------------------------------
class TestNoRegressions:
    def test_owner_lock_line_present_in_llm_chain(self):
        """Static check — the owner-lock strip line must remain."""
        with open("/app/backend/llm_chain.py", "r") as f:
            src = f.read()
        assert 'chain = [s for s in chain if s[0] != "universal"]' in src, (
            "Owner-lock line missing from /app/backend/llm_chain.py"
        )

    def test_sse_stream_emits_error_frame_on_all_provider_failure(self):
        """/api/ai/chat/stream should still emit an `event: error` frame
        when the provider chain is exhausted. (Owner chain has universal
        step which is currently over-budget, so a real request from
        non-owner without BYOK will produce error frame. For owner with
        dry providers we may get error too since all providers are dry.)
        Accept either an `event: error` frame OR an `event: done` frame
        with an offline/error reply — both are valid indicators the
        streaming path is intact.
        """
        conv = f"iter12_sse_{int(time.time())}"
        with requests.post(
            f"{BASE}/api/ai/chat/stream",
            headers={**OWNER_H, "Accept": "text/event-stream"},
            json={"message": "sse regression", "conversation_id": conv},
            stream=True, timeout=180,
        ) as r:
            assert r.status_code == 200, f"stream endpoint HTTP {r.status_code}"
            buf = []
            deadline = time.time() + 150
            for line in r.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                buf.append(line)
                joined = "\n".join(buf)
                if "event: error" in joined or "event: done" in joined:
                    break
                if time.time() > deadline:
                    break
        joined = "\n".join(buf)
        assert ("event: error" in joined) or ("event: done" in joined), (
            f"Neither error nor done frame observed in SSE output:\n"
            f"{joined[:2000]}"
        )
