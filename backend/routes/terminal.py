"""Terminal routes — HTTP 1-shot exec + interactive WebSocket PTY session."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from deps import consume_override, get_current_user, project_path, user_from_token
from core.destructive import scan_command
from core.pty_session import PtySession

router = APIRouter()


@router.post("/terminal/exec")
async def terminal_exec(payload: dict, user: dict = Depends(get_current_user)):
    project_id = payload.get("project_id", "")
    cmd = payload.get("command", "").strip()
    override_token = payload.get("override_token")
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    base = project_path(user["user_id"], project_id)

    matches = scan_command(cmd)
    has_critical = any(m.severity == "critical" for m in matches)
    has_high = any(m.severity == "high" for m in matches)

    if has_critical or has_high:
        allowed = await consume_override(user["user_id"], override_token)
        if not allowed:
            return JSONResponse(
                status_code=423,
                content={
                    "blocked": True,
                    "severity": "critical" if has_critical else "high",
                    "matches": [
                        {"pattern": m.pattern, "reason": m.reason,
                         "snippet": m.snippet, "line": m.line, "severity": m.severity}
                        for m in matches
                    ],
                    "message": "INTEGRITY HALT - destructive command detected. Password override required.",
                },
            )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        return {"stdout": "", "stderr": "Timeout (300s) — for long-running daemons use the interactive terminal.", "exit_code": 124}
    except OSError as e:
        return {"stdout": "", "stderr": f"Exec error: {e}", "exit_code": 1}


# ---------- Interactive PTY WebSocket ----------

_MAX_SHELLS_PER_USER = 5
_user_shell_count: dict[str, int] = {}


def register_ws(app) -> None:
    """Register the /api/terminal/ws WebSocket on the underlying FastAPI app.

    APIRouter.websocket() works with include_router, but for consistency with
    the previous direct @app.websocket binding (and clearer path handling for
    the kube ingress), we expose this helper invoked from server.py.
    """

    @app.websocket("/api/terminal/ws")
    async def terminal_ws(
        websocket: WebSocket,
        project_id: str = Query(...),
        token: Optional[str] = Query(default=None),
    ):
        cookie_token = websocket.cookies.get("session_token")
        user = await user_from_token(token, cookie_token)
        if not user:
            await websocket.close(code=4401)
            return

        uid = user["user_id"]
        if _user_shell_count.get(uid, 0) >= _MAX_SHELLS_PER_USER:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "msg": f"too many open shells ({_MAX_SHELLS_PER_USER}/user) — close an existing terminal first.",
            })
            await websocket.close(code=4429)
            return

        base = project_path(user["user_id"], project_id)
        await websocket.accept()
        _user_shell_count[uid] = _user_shell_count.get(uid, 0) + 1

        session = PtySession(cwd=str(base))
        try:
            await session.start()
        except OSError as e:
            await websocket.send_json({"type": "error", "msg": f"shell start failed: {e}"})
            await websocket.close()
            return

        async def pump_pty_to_ws():
            while not session.closed:
                data = await session.read()
                if not data:
                    break
                try:
                    await websocket.send_bytes(data)
                except (WebSocketDisconnect, RuntimeError):
                    break

        async def pump_ws_to_pty():
            try:
                while not session.closed:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "text" in msg and msg["text"] is not None:
                        try:
                            ctrl = json.loads(msg["text"])
                        except (ValueError, TypeError):
                            session.write(msg["text"].encode("utf-8"))
                            continue
                        if ctrl.get("type") == "resize":
                            session.set_size(int(ctrl.get("cols", 80)),
                                             int(ctrl.get("rows", 24)))
                        elif ctrl.get("type") == "input":
                            session.write(str(ctrl.get("data", "")).encode("utf-8"))
                    elif "bytes" in msg and msg["bytes"] is not None:
                        session.write(msg["bytes"])
            except WebSocketDisconnect:
                pass

        pty_task = asyncio.create_task(pump_pty_to_ws())
        ws_task = asyncio.create_task(pump_ws_to_pty())
        try:
            done, pending = await asyncio.wait(
                {pty_task, ws_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            session.close()
            for t in pending:
                t.cancel()
            for t in pending:
                try:
                    await t
                except (asyncio.CancelledError, WebSocketDisconnect, OSError):
                    pass
        finally:
            session.close()
            _user_shell_count[uid] = max(0, _user_shell_count.get(uid, 1) - 1)
            try:
                await websocket.close()
            except RuntimeError:
                pass
