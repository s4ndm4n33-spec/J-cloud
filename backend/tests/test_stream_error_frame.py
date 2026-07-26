"""Regression: SSE heartbeat wrapper must emit an `event: error` frame when
the wrapped task raises ANY exception — not just HTTPException. Previously
generic exceptions escaped, the generator died silently, and the client
hung until Cloudflare cut the connection at ~100s (surfaced as "voice
transcribed but no response returns").
"""
import asyncio
import pytest
from fastapi import HTTPException

from routes.ai import _stream_task_with_heartbeats


async def _collect(gen):
    frames = []
    async for f in gen:
        frames.append(f)
    return frames


@pytest.mark.asyncio
async def test_generic_exception_emits_error_frame():
    async def _boom():
        raise RuntimeError("upstream LLM exploded")

    frames = await _collect(_stream_task_with_heartbeats(_boom))
    # Must include an error frame with the exception message
    joined = "".join(frames)
    assert "event: error" in joined, f"no error frame emitted: {joined!r}"
    assert "upstream LLM exploded" in joined
    assert "stream_task_failed" in joined


@pytest.mark.asyncio
async def test_http_exception_still_emits_error_frame():
    async def _http():
        raise HTTPException(status_code=429, detail={"code": "rate_limited"})

    frames = await _collect(_stream_task_with_heartbeats(_http))
    joined = "".join(frames)
    assert "event: error" in joined
    assert "429" in joined
    assert "rate_limited" in joined


@pytest.mark.asyncio
async def test_success_emits_done_frame():
    async def _ok():
        return {"reply": "hello", "conversation_id": "c1"}

    frames = await _collect(_stream_task_with_heartbeats(_ok))
    joined = "".join(frames)
    assert "event: done" in joined
    assert "hello" in joined
