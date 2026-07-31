"""Verify /api/auth/me returns is_owner flag correctly for owner vs regular user."""
import os
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gauntlet-devspace.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
OWNER_USER_ID = "user_5d2818f635a9"
OWNER_TOKEN = "test_owner_session_001"
REG_TOKEN = "test_session_devspace_001"


async def _seed_owner():
    cli = AsyncIOMotorClient(MONGO_URL)
    d = cli[DB_NAME]
    await d.users.update_one(
        {"user_id": OWNER_USER_ID},
        {"$setOnInsert": {
            "user_id": OWNER_USER_ID,
            "email": "owner@sovereign.shards",
            "name": "Owner",
            "picture": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    await d.user_sessions.update_one(
        {"session_token": OWNER_TOKEN},
        {"$set": {
            "user_id": OWNER_USER_ID,
            "session_token": OWNER_TOKEN,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    cli.close()


@pytest.fixture(scope="module", autouse=True)
def seed_owner():
    asyncio.run(_seed_owner())
    yield


def test_auth_me_owner_returns_is_owner_true():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("user_id") == OWNER_USER_ID
    assert data.get("is_owner") is True, f"Expected is_owner True, got: {data}"


def test_auth_me_regular_user_returns_is_owner_false():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {REG_TOKEN}"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("user_id") != OWNER_USER_ID
    assert data.get("is_owner") is False, f"Expected is_owner False, got: {data}"


def test_auth_me_unauthenticated_401():
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code in (401, 403)
