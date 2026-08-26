from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from core.keyvault import decrypt_key, encrypt_key
from deps import db, get_current_user

router = APIRouter()


@router.post("/proposal")
async def send_proposal(
    payload: dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
):
    """
    Sends an encrypted proposal to the j_tunnel collection.
    """
    message = payload.get("message")
    sender = payload.get("sender", "preview-j")

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Using the existing Fernet-backed keyvault logic
    encrypted_message = encrypt_key(message)

    entry = {
        "sender": sender,
        "user_id": user["user_id"],
        "payload": encrypted_message,
        "timestamp": datetime.datetime.now(datetime.timezone.utc),
        "read": False,
    }

    await db.j_tunnel.insert_one(entry)
    return {"status": "ok", "message": "Proposal sent to tunnel"}


@router.get("/read")
async def read_tunnel(limit: int = 10, user: dict = Depends(get_current_user)):
    """
    Reads and decrypts messages from the j_tunnel collection.
    """
    cursor = db.j_tunnel.find({"user_id": user["user_id"]}).sort("timestamp", -1).limit(limit)
    docs = await cursor.to_list(limit)
    
    results = []
    for doc in docs:
        try:
            payload = decrypt_key(doc["payload"])
            results.append({
                "sender": doc["sender"],
                "payload": payload,
                "timestamp": doc["timestamp"].isoformat() if isinstance(doc["timestamp"], datetime.datetime) else doc["timestamp"],
            })
        except Exception:
            continue
            
    return results
