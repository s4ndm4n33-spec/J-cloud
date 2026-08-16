"""Auth routes — Emergent Google OAuth session exchange + logout."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from config import settings
from deps import db, get_current_user
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter()

EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@router.post("/auth/local/init")
async def auth_local_init(payload: dict, response: Response):
    """Initialize the first portable local operator and create a session."""
    if not settings.local_auth:
        raise HTTPException(status_code=404, detail="Local auth disabled")
    existing = await db.users.find_one({"auth_provider": "local"}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Local operator already initialized")
    email = (payload.get("email") or "operator@local.shard").strip().lower()
    name = (payload.get("name") or "Local Operator").strip()
    password = payload.get("password") or ""
    if len(password) < 12:
        raise HTTPException(status_code=400, detail="password must be at least 12 characters")
    user = {
        "user_id": f"local_{uuid.uuid4().hex[:12]}",
        "email": email,
        "name": name,
        "picture": "",
        "auth_provider": "local",
        "password_hash": pwd_context.hash(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(user))
    user.pop("password_hash", None)
    token = await _create_local_session(user["user_id"], response)
    return {"user": user, "session_token": token}


@router.post("/auth/local/login")
async def auth_local_login(payload: dict, response: Response):
    """Authenticate a portable local operator using SQLite-backed credentials."""
    if not settings.local_auth:
        raise HTTPException(status_code=404, detail="Local auth disabled")
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    user = await db.users.find_one({"email": email, "auth_provider": "local"}, {"_id": 0})
    if not user or not pwd_context.verify(password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid local credentials")
    token = await _create_local_session(user["user_id"], response)
    user.pop("password_hash", None)
    return {"user": user, "session_token": token}


async def _create_local_session(user_id: str, response: Response) -> str:
    session_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_provider": "local",
    })
    response.set_cookie(
        key="session_token", value=session_token, path="/",
        max_age=7 * 24 * 3600, httponly=True, secure=not settings.portable, samesite="lax",
    )
    return session_token


@router.post("/auth/session")
async def auth_session(payload: dict, response: Response):
    """Exchange Emergent session_id for a session_token cookie."""
    if settings.portable:
        raise HTTPException(status_code=404, detail="Emergent auth disabled in portable profile")
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Emergent auth failed: {r.text}")
    data = r.json()

    email = data["email"]
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name", email.split("@")[0]),
            "picture": data.get("picture", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(dict(user))
        user.pop("_id", None)
    else:
        await db.users.update_one(
            {"email": email},
            {"$set": {"name": data.get("name", user["name"]),
                      "picture": data.get("picture", user.get("picture", ""))}},
        )

    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    response.set_cookie(
        key="session_token", value=session_token, path="/",
        max_age=7 * 24 * 3600, httponly=True, secure=True, samesite="none",
    )
    return {"user": user, "session_token": session_token}


@router.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return user


@router.post("/auth/logout")
async def auth_logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}
