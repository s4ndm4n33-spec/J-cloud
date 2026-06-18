"""Shared test session re-seed fixture.

The iter3 logout fix actually invalidates the server-side session when
logout is called with only a Bearer header. The iter3 test suite calls
that logout — if other tests run after it, they would 401. This fixture
re-seeds the test session before every test so the suite is order-safe.
"""
import os
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

TOKEN = "test_session_devspace_001"
USER_ID = "user_test_devspace"
EMAIL = "test.j@sovereign.shards"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


async def _reseed():
    cli = AsyncIOMotorClient(MONGO_URL)
    d = cli[DB_NAME]
    await d.users.update_one(
        {"user_id": USER_ID},
        {"$setOnInsert": {
            "user_id": USER_ID,
            "email": EMAIL,
            "name": "Test J",
            "picture": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    await d.user_sessions.update_one(
        {"session_token": TOKEN},
        {"$set": {
            "user_id": USER_ID,
            "session_token": TOKEN,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    cli.close()


@pytest.fixture(autouse=True)
def reseed_session():
    asyncio.run(_reseed())
    yield
