"""Five Masters AST + destructive-code interlock routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, OVERRIDE_PASSWORD
from core.destructive import scan as destructive_scan
from core.fivemasters import evaluate as fm_evaluate

router = APIRouter()


@router.post("/gauntlet/evaluate")
async def gauntlet_evaluate(payload: dict, user: dict = Depends(get_current_user)):
    code = payload.get("code", "")
    language = payload.get("language", "python")
    report = fm_evaluate(code, language)
    return report.to_dict()


@router.post("/governance/scan")
async def governance_scan(payload: dict, user: dict = Depends(get_current_user)):
    code = payload.get("code") or payload.get("command") or ""
    matches = destructive_scan(code)
    return {
        "blocked": any(m.severity == "critical" for m in matches),
        "warn": any(m.severity == "high" for m in matches),
        "matches": [
            {"pattern": m.pattern, "line": m.line, "snippet": m.snippet,
             "severity": m.severity, "reason": m.reason} for m in matches
        ],
    }


@router.post("/governance/override")
async def governance_override(payload: dict, user: dict = Depends(get_current_user)):
    """Verify password to permit a destructive op."""
    if payload.get("password", "") != OVERRIDE_PASSWORD:
        await db.override_log.insert_one({
            "user_id": user["user_id"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "outcome": "rejected",
            "intent": payload.get("intent", ""),
        })
        raise HTTPException(status_code=403, detail="Override password incorrect")
    token = f"ovr_{uuid.uuid4().hex[:20]}"
    await db.overrides.insert_one({
        "token": token,
        "user_id": user["user_id"],
        "intent": payload.get("intent", ""),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    })
    await db.override_log.insert_one({
        "user_id": user["user_id"],
        "ts": datetime.now(timezone.utc).isoformat(),
        "outcome": "granted",
        "intent": payload.get("intent", ""),
    })
    return {"override_token": token, "expires_in": 120}
