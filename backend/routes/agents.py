"""BYO agents — user-defined LLM personas saved to the workspace."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user
from core.keyvault import encrypt_key

router = APIRouter()


@router.get("/agents")
async def list_agents(user: dict = Depends(get_current_user)):
    docs = await db.user_agents.find(
        {"user_id": user["user_id"]}, {"_id": 0, "endpoint_key_ct": 0}
    ).to_list(50)
    return {"agents": docs}


@router.post("/agents")
async def create_agent(payload: dict, user: dict = Depends(get_current_user)):
    name = (payload.get("name") or "").strip()
    system_prompt = payload.get("system_prompt") or ""
    provider = payload.get("provider", "gemini")
    model = payload.get("model") or "gemini-3-flash-preview"
    endpoint = payload.get("endpoint")
    endpoint_key = payload.get("endpoint_key")
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    doc = {
        "agent_id": agent_id,
        "user_id": user["user_id"],
        "name": name,
        "system_prompt": system_prompt,
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if endpoint_key:
        doc["endpoint_key_ct"] = encrypt_key(endpoint_key)
    await db.user_agents.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("endpoint_key_ct", None)
    return doc


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, user: dict = Depends(get_current_user)):
    await db.user_agents.delete_one({"agent_id": agent_id, "user_id": user["user_id"]})
    return {"ok": True}
