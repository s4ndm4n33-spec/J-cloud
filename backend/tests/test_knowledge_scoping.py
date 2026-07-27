"""Regression: J:MIND per-user scoping.

Before 2026-02, `knowledge_facts` was global — one user's Tavily auto-learn
would surface in another user's LLM prompt via `km.recall`. These tests
lock in the scoping contract:

- User A's private fact NEVER surfaces for user B (recall or list).
- A fact marked `shared=True` DOES surface for everyone.
- Non-owner cannot delete another user's fact.
- Owner sees everything.
- The legacy-migration helper is idempotent.
"""
import os
import asyncio
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core import knowledge as km

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture
async def db():
    cli = AsyncIOMotorClient(MONGO_URL)
    d = cli[DB_NAME + "_scoping_test"]
    # Clean slate every test
    await d.knowledge_facts.delete_many({})
    await d.knowledge_proposals.delete_many({})
    await km._ensure_indexes(d)
    yield d
    await d.knowledge_facts.delete_many({})
    await d.knowledge_proposals.delete_many({})
    cli.close()


USER_A = "user_alice_test"
USER_B = "user_bob_test"
OWNER = "user_owner_test"


@pytest.mark.asyncio
async def test_private_fact_isolated_between_users(db):
    """User A adds a private fact. User B must NOT see it via recall or list."""
    await km.add_fact(
        db, user_id=USER_A,
        title="Alice's diesel torque spec",
        body="6.7L Cummins head bolt torque: 132 lbf-ft plus 90 degrees.",
        category="mechanical", shared=False,
    )

    # User B's recall must be empty
    hits_b = await km.recall(db, "cummins torque",
                             user_id=USER_B, is_owner=False, k=5)
    assert hits_b == [], f"LEAK — user B saw user A's fact: {hits_b}"

    # User B's list must be empty
    list_b = await km.list_facts(db, user_id=USER_B, is_owner=False)
    assert list_b == [], f"LEAK — list_facts leaked to user B: {list_b}"

    # User A CAN see their own
    hits_a = await km.recall(db, "cummins torque",
                             user_id=USER_A, is_owner=False, k=5)
    assert len(hits_a) == 1 and "Alice" in hits_a[0]["title"]


@pytest.mark.asyncio
async def test_shared_fact_visible_to_all(db):
    """Fact with `shared=True` surfaces for every non-owner."""
    await km.add_fact(
        db, user_id=OWNER,
        title="Five Masters axiom",
        body="Deterministic output regardless of the underlying LLM.",
        category="doctrine", shared=True,
    )
    for uid in (USER_A, USER_B):
        hits = await km.recall(db, "five masters",
                               user_id=uid, is_owner=False, k=5)
        assert len(hits) == 1, f"shared fact missing for {uid}: {hits}"


@pytest.mark.asyncio
async def test_owner_sees_everything(db):
    """Owner (is_owner=True) sees both user A's private and user B's private."""
    await km.add_fact(db, user_id=USER_A, title="A private", body="Alice private.")
    await km.add_fact(db, user_id=USER_B, title="B private", body="Bob private.")
    hits = await km.recall(db, "private",
                           user_id=OWNER, is_owner=True, k=5)
    titles = {h["title"] for h in hits}
    assert {"A private", "B private"}.issubset(titles), (
        f"owner should see both: got {titles}"
    )


@pytest.mark.asyncio
async def test_non_owner_cannot_delete_other_users_fact(db):
    """Bob cannot delete Alice's fact."""
    r = await km.add_fact(db, user_id=USER_A,
                          title="A private", body="Alice private.")
    fact_id = r["id"]
    r_del = await km.delete_fact(db, fact_id, user_id=USER_B, is_owner=False)
    assert r_del["ok"] is False, "non-owner deleted another user's fact"
    # Fact still exists
    still = await db.knowledge_facts.find_one({"id": fact_id})
    assert still is not None


@pytest.mark.asyncio
async def test_owner_can_delete_any_fact(db):
    """Owner deletes anyone's fact."""
    r = await km.add_fact(db, user_id=USER_A,
                          title="A private", body="Alice private.")
    r_del = await km.delete_fact(db, r["id"], user_id=OWNER, is_owner=True)
    assert r_del["ok"] is True


@pytest.mark.asyncio
async def test_share_fact_owner_only(db):
    """share_fact rejects non-owners; accepts owner."""
    r = await km.add_fact(db, user_id=USER_A,
                          title="A", body="body body body")
    fid = r["id"]
    bad = await km.share_fact(db, fid, is_owner=False)
    assert "error" in bad
    good = await km.share_fact(db, fid, is_owner=True, shared=True)
    assert good["ok"] is True
    doc = await db.knowledge_facts.find_one({"id": fid})
    assert doc["shared"] is True


@pytest.mark.asyncio
async def test_migration_idempotent(db):
    """Migrate an unscoped legacy fact, then re-run — no double-touching."""
    await db.knowledge_facts.insert_one({
        "id": "fact_legacy_1", "title": "legacy",
        "body": "no user_id set", "category": "general",
        "ts": "2020-01-01T00:00:00+00:00",
    })
    r1 = await km.migrate_legacy_facts(db, OWNER)
    assert r1["migrated_facts"] == 1
    r2 = await km.migrate_legacy_facts(db, OWNER)
    assert r2["migrated_facts"] == 0
    doc = await db.knowledge_facts.find_one({"id": "fact_legacy_1"})
    assert doc["user_id"] == OWNER
    assert doc["shared"] is True


@pytest.mark.asyncio
async def test_auto_learn_scopes_to_user(db):
    """auto_learn_from_search must stamp user_id + shared on every fact."""
    fake_search = {
        "query": "opus 4.7 release notes",
        "results": [{
            "title": "Anthropic Opus 4.7 release notes",
            "url": "https://example.com/opus",
            "content": "Opus 4.7 released 2026-01-15 with " + "x" * 250,
            "score": 0.9,
        }],
    }
    # User B triggers a search — must be private to them
    r = await km.auto_learn_from_search(db, fake_search,
                                        user_id=USER_B, shared=False)
    assert r["learned"] >= 1
    docs = await db.knowledge_facts.find(
        {"source_url": "https://example.com/opus"}
    ).to_list(10)
    for d in docs:
        assert d["user_id"] == USER_B, f"leaked user_id: {d.get('user_id')}"
        assert d["shared"] is False, "auto-learn should not auto-share"


@pytest.mark.asyncio
async def test_propose_shared_owner_promotes_to_shared(db):
    """User B proposes a shared fact; owner accepts → fact is shared → user A sees it."""
    prop = await km.add_proposal(
        db, title="Public torque spec",
        body="A universally useful torque value everyone should know.",
        category="mechanical", user_id=USER_B,
        propose_shared=True,
    )
    r = await km.resolve_proposal(
        db, prop["id"], "accept",
        caller_user_id=OWNER, is_owner=True,
    )
    assert r.get("ok") and r.get("shared") is True

    # User A must now see it via recall
    hits = await km.recall(db, "torque spec",
                           user_id=USER_A, is_owner=False, k=5)
    assert any("Public torque spec" == h["title"] for h in hits), (
        f"owner-accepted shared proposal not visible to user A: {hits}"
    )


@pytest.mark.asyncio
async def test_propose_shared_non_owner_accept_stays_private(db):
    """If a non-owner accepts their OWN propose_shared proposal, the resulting
    fact must stay private — only the owner can promote to shared baseline.
    This prevents users from self-approving public knowledge.
    """
    # User B proposes with propose_shared=True
    prop = await km.add_proposal(
        db, title="Would-be public",
        body="User B thinks this should be public.",
        category="general", user_id=USER_B,
        propose_shared=True,
    )
    # User B accepts their own proposal (non-owner)
    r = await km.resolve_proposal(
        db, prop["id"], "accept",
        caller_user_id=USER_B, is_owner=False,
    )
    assert r.get("ok") and r.get("shared") is False, (
        "non-owner accept must NOT promote propose_shared to shared"
    )
    # User A must NOT see it
    hits = await km.recall(db, "public",
                           user_id=USER_A, is_owner=False, k=5)
    assert not any("Would-be public" == h["title"] for h in hits), (
        "non-owner self-accepted propose_shared leaked to another user"
    )
