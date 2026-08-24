"""Promo warmup — pre-primes the two demo projects the Builder Fest promo
manifest expects (see /app/docs/promo/builderfest-promo-manifest.md).

The director agent hits `POST /api/promo/warmup`, gets back two project IDs
and direct IDE URLs, and starts recording. Idempotent: existing demo
projects with the same names are torn down and rebuilt fresh so every take
starts from the same known state.
"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from deps import db, get_current_user, seed_project, user_root, safe_join

router = APIRouter()

# The manifest hard-codes these names — do not rename without updating
# Shot 03 (Builder Fest Demo) and Shot 06 (Unsafe Ship-It) in the manifest.
DEMO_A_NAME = "Builder Fest Demo"
DEMO_B_NAME = "Unsafe Ship-It"

# 6 lines of intentionally boring code — the "before" state for Shot 03.
# J is going to overwrite this when the user types the fibonacci prompt.
_HELLO_PY = '''\
"""Builder Fest demo starter — J will replace this."""


def main() -> None:
    print("hello, builder fest")


if __name__ == "__main__":
    main()
'''

# The intentionally-unsafe file for Shot 06 (gauntlet HALT verdict).
# `os.system(user_input)` is a textbook shell-injection destructive pattern
# the gauntlet AST scanner catches. Do not "fix" this file — the whole
# point is that shipping it should be halted.
_UNSAFE_PY = '''\
"""Shot 06 fixture — the gauntlet HALTs this on a `ship it` prompt."""
import os
import sys


def main() -> None:
    user_input = sys.argv[1] if len(sys.argv) > 1 else ""
    # DELIBERATELY UNSAFE — shell injection surface. Do not fix.
    os.system(user_input)


if __name__ == "__main__":
    main()
'''


async def _teardown_by_name(user_id: str, name: str) -> None:
    """Delete every project the caller owns with this exact name.
    Ensures each promo take starts from a known blank slate."""
    cursor = db.projects.find({"user_id": user_id, "name": name}, {"_id": 0})
    async for proj in cursor:
        pid = proj["project_id"]
        disk = user_root(user_id) / pid
        if disk.exists():
            shutil.rmtree(disk, ignore_errors=True)
        await db.projects.delete_one({"project_id": pid, "user_id": user_id})


async def _create_seeded(user_id: str, name: str, extra_files: dict[str, str]) -> str:
    """Create a fresh project, seed it, then overwrite/add the extra files.
    Returns the new project_id."""
    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    path = user_root(user_id) / project_id
    seed_project(path)  # baseline scaffold + `git init`
    for rel, content in extra_files.items():
        target = safe_join(path, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    await db.projects.insert_one({
        "project_id": project_id,
        "user_id": user_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return project_id


@router.post("/promo/warmup")
async def promo_warmup(user: dict = Depends(get_current_user)):
    """Owner-only. Rebuilds the two demo projects from scratch and returns
    their IDs + preview IDE URLs so the director agent can navigate straight
    into recording without any manual setup.

    Deterministic. Idempotent. Silent about non-existent teardowns.
    """
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="owner_only")

    await _teardown_by_name(user["user_id"], DEMO_A_NAME)
    await _teardown_by_name(user["user_id"], DEMO_B_NAME)

    demo_a = await _create_seeded(
        user["user_id"], DEMO_A_NAME,
        {"hello.py": _HELLO_PY},
    )
    demo_b = await _create_seeded(
        user["user_id"], DEMO_B_NAME,
        {"unsafe.py": _UNSAFE_PY},
    )

    # Frontend routes projects at /ide?project=<id>. The director just
    # loads this URL after setting the session cookie.
    return {
        "ok": True,
        "reset_at": datetime.now(timezone.utc).isoformat(),
        "demo_a": {
            "name": DEMO_A_NAME,
            "project_id": demo_a,
            "ide_url": f"/ide?project={demo_a}",
            "seeded_files": ["hello.py"],
            "used_in_shots": ["03", "04", "05"],
            "prompt_for_j": (
                'build me a fibonacci CLI with a test suite and commit it '
                'with message "feat: fibonacci CLI + tests"'
            ),
        },
        "demo_b": {
            "name": DEMO_B_NAME,
            "project_id": demo_b,
            "ide_url": f"/ide?project={demo_b}",
            "seeded_files": ["unsafe.py"],
            "used_in_shots": ["06"],
            "prompt_for_j": "ship it",
            "expected_gauntlet_verdict": "HALT · destructive_pattern · shell_injection",
        },
    }
