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

from deps import client, db, OWNER_USER_ID  # noqa: F401  (db imported to ensure indexes attach)
from core import chronicle as chron
from core import ambient
from core.ratelimit import set_owner_id as _set_rl_owner
from routes import (
    admin, agent_tunnel as agent_tunnel_routes, agents, ai,
    ambient as ambient_routes, audit, auth, chronicle,
    gauntlet, git_local, github, knowledge, projects, reports, settings, terminal,
    training, training_webhooks, uploads, voice,
)

_set_rl_owner(OWNER_USER_ID)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("gauntlet")

app = FastAPI(title="Gauntlet DevSpace API")
api = APIRouter(prefix="/api")

# Mount every route module under /api
for module in (
    auth, projects, gauntlet, terminal, git_local, settings,
    chronicle, ai, github, audit, uploads, agents, ambient_routes, voice,
    knowledge, admin, training, training_webhooks, reports,
    agent_tunnel_routes,
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
    # ------------------------------------------------------------------
    # Runtime git install fallback.
    #
    # /app/.emergent/system_deps.txt is the DECLARED path for OS packages,
    # but an Emergent platform auto-commit is currently reverting any
    # addition beyond `cron=3.0pl1-162` (verified — commits b6c81aa/5e9c06d
    # stripped `git=1:2.39.5-0+deb12u3` immediately after we added it).
    # Until Emergent Support un-locks the manifest, we self-install at
    # boot. GitPython + our agent_tunnel apply_diff both need the binary.
    # Idempotent: if `git` is already on PATH we skip the apt call.
    # ------------------------------------------------------------------
    try:
        import shutil, subprocess  # local import — keeps top-of-file tidy
        if shutil.which("git"):
            log.info(f"git present: {shutil.which('git')}")
        else:
            log.warning("git missing at startup — attempting runtime install")
            def _try_install(extra_args: list[str]) -> tuple[int, str]:
                r = subprocess.run(
                    ["apt-get", "install", "-y", "--no-install-recommends", *extra_args, "git"],
                    capture_output=True, text=True, timeout=90,
                )
                return r.returncode, (r.stderr or "")

            rc, err = _try_install([])
            if rc != 0 or not shutil.which("git"):
                # Refresh package lists and retry once.
                subprocess.run(["apt-get", "update", "-y"], capture_output=True, timeout=60)
                rc, err = _try_install([])
            if not shutil.which("git"):
                # apt reports success but binary isn't there — try --reinstall.
                rc, err = _try_install(["--reinstall"])
            if shutil.which("git"):
                log.info(f"git installed at runtime: {shutil.which('git')}")
            else:
                log.error(f"git runtime install FAILED (rc={rc}): {err[:500]} "
                          f"— GitPython + apply_diff will not work until "
                          f"Emergent Support restores the manifest")
    except Exception as e:
        log.warning(f"git runtime install path errored: {e}")

    try:
        await chron.ensure_indexes(db)
    except Exception as e:
        log.warning(f"chronicle indexes setup failed: {e}")
    # Compound index for ambient events (user + ts newest-first)
    try:
        await db.ambient_events.create_index([("user_id", 1), ("ts", -1)])
        await db.ambient_events.create_index("event_key")
    except Exception as e:
        log.warning(f"ambient_events indexes setup failed: {e}")
    # J:MIND — ensure per-user scoping indexes exist and migrate legacy
    # (pre-scoping) facts into the owner's shared baseline. Idempotent.
    try:
        from core import knowledge as km
        await km._ensure_indexes(db)
        owner_id = os.environ.get("OWNER_USER_ID", "").strip()
        if owner_id:
            r = await km.migrate_legacy_facts(db, owner_id)
            if r.get("migrated_facts") or r.get("migrated_proposals"):
                log.info(f"j:mind migration: {r}")
    except Exception as e:
        log.warning(f"j:mind scoping migration failed: {e}")
    # Workspace persistence — index the projects.last_activity field for the
    # periodic sync loop, then start the loop. If R2 isn't configured the
    # loop is a no-op (see workspace_sync.SyncLoop.start).
    try:
        await db.projects.create_index([("last_activity", -1)])
        await db.project_snapshots.create_index(
            [("project_id", 1), ("ts", -1)]
        )
        from core import workspace_sync as wsync
        from deps import project_path as _pp
        wsync.sync_loop.start(db, _pp, interval_sec=300)
    except Exception as e:
        log.warning(f"workspace-sync bootstrap failed: {e}")
    # Agent tunnel — cross-pod ticket bus (prev-J <-> prod-J via R2).
    # Sync loop polls R2 every 30s and upserts new tickets into local Mongo.
    try:
        from core import agent_tunnel as at
        await at.ensure_indexes(db)
        at.tunnel_sync.start(db, interval_sec=30)
    except Exception as e:
        log.warning(f"agent-tunnel bootstrap failed: {e}")
    # Boot the ambient-awareness detector
    ambient.start()


@app.on_event("shutdown")
async def _shutdown():
    ambient.stop()
    try:
        from core import workspace_sync as wsync
        wsync.sync_loop.stop()
    except Exception:
        pass
    try:
        from core import agent_tunnel as at
        at.tunnel_sync.stop()
    except Exception:
        pass
    client.close()
