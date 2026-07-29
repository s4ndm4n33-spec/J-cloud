"""Regression: eidetic memory / conversation rehydration from Mongo.

Before this fix, `_ai_chat_impl` relied on the LLM SDK's in-process session
cache (keyed by user+conversation_id) to remember prior turns. That cache
died on:
  - pod restart
  - LLM chain retry to a different provider
  - server-side amnesia across refreshes

This test locks in the fix: on every /ai/chat call, the server pulls prior
turns of the same conversation_id from Mongo and prepends them to the
prompt. J's black box is Mongo, not the SDK's RAM.
"""
import os
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture
async def db():
    cli = AsyncIOMotorClient(MONGO_URL)
    d = cli[DB_NAME + "_eidetic_test"]
    await d.messages.delete_many({})
    yield d
    await d.messages.delete_many({})
    cli.close()


@pytest.mark.asyncio
async def test_chat_impl_rehydrates_prior_turns_from_mongo(db, monkeypatch):
    """Simulate a mid-conversation call and assert the transcript passed to
    the LLM includes the prior user+assistant turns from Mongo."""
    from routes import ai as ai_mod

    conv_id = "conv_eidetic_test_1"
    user = {"user_id": "user_eidetic_test"}

    # Seed Mongo with 4 prior turns of the same conversation.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.messages.insert_many([
        {"conversation_id": conv_id, "user_id": user["user_id"], "role": "user",
         "content": "hi J, remember my project name is Odyssey.", "ts": now},
        {"conversation_id": conv_id, "user_id": user["user_id"], "role": "assistant",
         "content": "Locked in — 'Odyssey'.", "ts": now},
        {"conversation_id": conv_id, "user_id": user["user_id"], "role": "user",
         "content": "and my deploy target is Fly.io", "ts": now},
        {"conversation_id": conv_id, "user_id": user["user_id"], "role": "assistant",
         "content": "Fly.io noted.", "ts": now},
    ])

    # Patch `db` inside routes.ai module so the impl uses our test collection.
    monkeypatch.setattr(ai_mod, "db", db)

    # Patch chain_call so we can capture what transcript was sent to the LLM
    # without touching a real provider.
    captured = {}
    async def fake_chain_call(user_id, task, system, user_text, session_id):
        captured["user_text"] = user_text
        captured["system"] = system
        return ("understood.", {"success": True, "model_used": "test",
                                 "provider_used": "test", "attempts": []})
    monkeypatch.setattr(ai_mod, "chain_call", fake_chain_call)

    # Patch km.recall to a no-op so we don't need the embedding model.
    async def fake_recall(*a, **kw):
        return []
    monkeypatch.setattr(ai_mod.km, "recall", fake_recall)

    # Patch rate limit to a no-op so tests never trip the bucket.
    monkeypatch.setattr(ai_mod, "ratelimit_take", lambda *a, **kw: None)

    payload = {"conversation_id": conv_id,
               "message": "what was my project name again?"}
    result = await ai_mod._ai_chat_impl(payload, user)

    # The prompt the LLM saw MUST contain the prior turns.
    ut = captured["user_text"]
    assert "Odyssey" in ut, f"prior user turn lost: {ut[:400]}"
    assert "Fly.io" in ut, f"second prior user turn lost: {ut[:400]}"
    assert "[J]" in ut, "assistant turns not tagged in transcript"
    assert "[USER]" in ut, "user turns not tagged in transcript"
    assert "CONVERSATION HISTORY" in ut, "history header missing"
    # Current message should still be at the end.
    assert ut.rstrip().endswith("what was my project name again?"), (
        f"current message not at tail of transcript: {ut[-200:]}"
    )
    # Sanity — the response is what we returned from the fake.
    assert result["reply"] == "understood."


@pytest.mark.asyncio
async def test_chat_impl_empty_conversation_no_history_block(db, monkeypatch):
    """First message of a brand-new conversation has no prior turns; the
    history block must NOT be injected (avoids a confusing empty header)."""
    from routes import ai as ai_mod

    user = {"user_id": "user_eidetic_test"}
    monkeypatch.setattr(ai_mod, "db", db)

    captured = {}
    async def fake_chain_call(user_id, task, system, user_text, session_id):
        captured["user_text"] = user_text
        return ("hi", {"success": True, "model_used": "test",
                       "provider_used": "test", "attempts": []})
    monkeypatch.setattr(ai_mod, "chain_call", fake_chain_call)
    async def fake_recall(*a, **kw):
        return []
    monkeypatch.setattr(ai_mod.km, "recall", fake_recall)
    monkeypatch.setattr(ai_mod, "ratelimit_take", lambda *a, **kw: None)

    payload = {"message": "hello"}
    await ai_mod._ai_chat_impl(payload, user)
    assert "CONVERSATION HISTORY" not in captured["user_text"]
