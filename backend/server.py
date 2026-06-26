"""Gauntlet DevSpace - Sovereign Shards cloud IDE backend.

FastAPI app shell. Routing logic lives in routes/*.py and shared helpers
in deps.py, llm_chain.py, chronicle_helpers.py.

Endpoints provided:
- Emergent Google OAuth (sessions)
- Project workspace + file CRUD
- Integrated terminal exec (with destructive code hard-block + password override)
- Interactive PTY terminal (WebSocket)
- AI Coworker: Gemini chat / GPT-5.2 refine / Claude Sonnet 4.5 governance / agent
- Five Masters AST evaluation + destructive governance
- Git (local + GitHub)
- Chronicle (flight-recorder), Audit, Memory, Uploads, BYO agents.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from deps import client, db  # noqa: F401  (db imported to ensure indexes attach)
from core import chronicle as chron
from routes import (
    agents, ai, audit, auth, chronicle, gauntlet, git_local, github,
    projects, settings, terminal, uploads,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("gauntlet")

app = FastAPI(title="Gauntlet DevSpace API")
api = APIRouter(prefix="/api")

# Mount every route module under /api
for module in (
    auth, projects, gauntlet, terminal, git_local, settings,
    chronicle, ai, github, audit, uploads, agents,
):
    api.include_router(module.router)


@api.get("/")
async def root():
    return {
        "name": "Gauntlet DevSpace",
        "tagline": "DETERMINISTIC. AUTONOMOUS. SUBSTRATE.",
        "status": "online",
    }


# WebSocket endpoint must be attached directly to the FastAPI app (not via APIRouter)
terminal.register_ws(app)

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    try:
        await chron.ensure_indexes(db)
    except Exception as e:
        log.warning(f"chronicle indexes setup failed: {e}")


@app.on_event("shutdown")
async def _shutdown():
    client.close()
