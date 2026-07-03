"""Settings (BYOK keys + Ollama), Tutorial state, Private Mode toggle."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, EMERGENT_LLM_KEY
from core.keyvault import SUPPORTED_PROVIDERS, encrypt_key, mask
from llm_chain import OLLAMA_PRESETS, resolve_byok, valid_local_url

router = APIRouter()


@router.get("/settings/keys")
async def list_keys(user: dict = Depends(get_current_user)):
    docs = await db.user_provider_keys.find(
        {"user_id": user["user_id"]}, {"_id": 0, "ciphertext": 0}
    ).to_list(20)
    have = {d["provider"]: d for d in docs}
    out = []
    for prov in SUPPORTED_PROVIDERS:
        if prov in have:
            d = have[prov]
            entry = {
                "provider": prov,
                "configured": True,
                "masked": d.get("masked", ""),
                "updated_at": d.get("updated_at"),
            }
            if prov == "ollama":
                entry["base_url"] = d.get("base_url", "")
                entry["default_model"] = d.get("default_model", "")
            out.append(entry)
        else:
            entry = {"provider": prov, "configured": False, "masked": "", "updated_at": None}
            if prov == "ollama":
                entry["base_url"] = ""
                entry["default_model"] = ""
            out.append(entry)
    return {
        "providers": out,
        "universal_key_available": bool(EMERGENT_LLM_KEY),
        "ollama_presets": OLLAMA_PRESETS,
    }


@router.put("/settings/keys")
async def set_key(payload: dict, user: dict = Depends(get_current_user)):
    provider = payload.get("provider", "")
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    if provider == "ollama":
        base_url = (payload.get("base_url") or "").strip()
        default_model = (payload.get("default_model") or "").strip()
        if not valid_local_url(base_url):
            raise HTTPException(status_code=400, detail="Invalid base URL (must start with http:// or https://)")
        if not default_model:
            raise HTTPException(status_code=400, detail="Default model is required (e.g., llama3.1)")
        doc = {
            "user_id": user["user_id"],
            "provider": provider,
            "base_url": base_url,
            "default_model": default_model,
            "masked": f"{base_url} · {default_model}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.user_provider_keys.update_one(
            {"user_id": user["user_id"], "provider": provider},
            {"$set": doc},
            upsert=True,
        )
        return {"ok": True, "provider": provider, "masked": doc["masked"]}

    api_key = (payload.get("api_key") or "").strip()
    if not api_key or len(api_key) < 12:
        raise HTTPException(status_code=400, detail="Invalid API key")
    doc = {
        "user_id": user["user_id"],
        "provider": provider,
        "ciphertext": encrypt_key(api_key),
        "masked": mask(api_key),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.user_provider_keys.update_one(
        {"user_id": user["user_id"], "provider": provider},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "provider": provider, "masked": doc["masked"]}


@router.delete("/settings/keys/{provider}")
async def delete_key(provider: str, user: dict = Depends(get_current_user)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    await db.user_provider_keys.delete_one(
        {"user_id": user["user_id"], "provider": provider}
    )
    return {"ok": True, "provider": provider}


@router.post("/settings/keys/ollama/test")
async def test_ollama(payload: dict, user: dict = Depends(get_current_user)):
    """Smoke-test the user's Ollama / llama.cpp endpoint."""
    base_url = (payload.get("base_url") or "").strip()
    if not valid_local_url(base_url):
        raise HTTPException(status_code=400, detail="Invalid base URL")
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=8.0) as http:
        try:
            r = await http.get(f"{base}/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return {"ok": True, "backend": "ollama", "models": models}
        except (httpx.HTTPError, ValueError):
            pass
        try:
            r = await http.get(f"{base}/v1/models")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                return {"ok": True, "backend": "openai-compat", "models": models}
        except (httpx.HTTPError, ValueError) as e:
            return {"ok": False, "error": f"Unreachable: {e}"}
    return {"ok": False, "error": "Endpoint did not respond to /api/tags or /v1/models"}


# ---------- Tutorial state ----------

@router.get("/me/tutorial")
async def tutorial_state(user: dict = Depends(get_current_user)):
    completed = bool(user.get("tutorial_completed", False))
    return {"completed": completed}


@router.post("/me/tutorial")
async def set_tutorial_state(payload: dict, user: dict = Depends(get_current_user)):
    completed = bool(payload.get("completed", True))
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"tutorial_completed": completed,
                  "tutorial_updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "completed": completed}


# ---------- Private Mode ----------

@router.get("/me/private-mode")
async def get_private_mode(user: dict = Depends(get_current_user)):
    enabled = bool(user.get("private_mode", False))
    ollama_cfg = await resolve_byok(user["user_id"], "ollama")
    return {"enabled": enabled, "ollama_ready": bool(ollama_cfg)}


@router.post("/me/private-mode")
async def set_private_mode(payload: dict, user: dict = Depends(get_current_user)):
    enabled = bool(payload.get("enabled", False))
    if enabled:
        ollama_cfg = await resolve_byok(user["user_id"], "ollama")
        if not ollama_cfg:
            raise HTTPException(
                status_code=400,
                detail="Link a local server (Ollama / llama.cpp) in Settings before enabling Private Mode.",
            )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"private_mode": enabled,
                  "private_mode_updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "enabled": enabled}
