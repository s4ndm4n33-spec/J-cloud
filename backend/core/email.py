"""Resend email integration — thin async wrapper.

Sends opt-in chat transcript emails on END SESSION. Designed to fail gracefully:
if RESEND_API_KEY is unset, `send_email` returns {ok: False, error: 'disabled'}
without raising so the close-session flow still works (just no email).

Sender selection: tries RESEND_FROM_PREFERRED first; falls back to
RESEND_FROM_VERIFIED (the sandbox sender) so we don't crash before DNS is wired.
We do NOT pre-check verification — Resend will reject and we surface the error.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

log = logging.getLogger("email")

try:
    import resend  # type: ignore
except ImportError:
    resend = None  # type: ignore


def _api_key() -> Optional[str]:
    k = (os.environ.get("RESEND_API_KEY") or "").strip()
    return k or None


def _from_addr() -> str:
    pref = (os.environ.get("RESEND_FROM_PREFERRED") or "").strip()
    fb = (os.environ.get("RESEND_FROM_VERIFIED") or "onboarding@resend.dev").strip()
    return pref or fb


async def send_email(
    *, to: str, subject: str, html: str, text: Optional[str] = None,
) -> dict:
    """Send one email. Returns {ok, id?, error?}."""
    if not _api_key():
        return {"ok": False, "error": "Resend not configured (RESEND_API_KEY missing)"}
    if resend is None:
        return {"ok": False, "error": "resend package not installed"}
    if not to or "@" not in to:
        return {"ok": False, "error": "invalid recipient"}

    resend.api_key = _api_key()
    sender = _from_addr()
    params = {
        "from": sender,
        "to": [to],
        "subject": subject[:240],
        "html": html,
    }
    if text:
        params["text"] = text

    try:
        # SDK is sync — run in a thread so we don't block the event loop.
        result = await asyncio.to_thread(resend.Emails.send, params)
    except Exception as e:  # noqa: BLE001 — Resend SDK raises a generic Exception
        msg = str(e)
        log.warning(f"resend send failed (from={sender} to={to}): {msg}")
        # If preferred sender is unverified, retry with sandbox fallback once.
        verified = (os.environ.get("RESEND_FROM_VERIFIED") or "").strip()
        if verified and sender != verified and (
            "domain is not verified" in msg.lower()
            or "validation" in msg.lower()
            or "from" in msg.lower()
        ):
            log.info(f"retrying with verified sandbox sender {verified}")
            params["from"] = verified
            try:
                result = await asyncio.to_thread(resend.Emails.send, params)
            except Exception as e2:  # noqa: BLE001
                return {"ok": False, "error": str(e2), "attempted_fallback": True}
        else:
            return {"ok": False, "error": msg}

    return {"ok": True, "id": (result or {}).get("id"), "from": params["from"]}


def render_transcript_html(
    *, project_name: str, session_id: str, narrative: str,
    messages: list[dict],
) -> tuple[str, str]:
    """Return (html, plain_text) for the transcript email."""
    short = session_id[-10:]
    text_lines = [
        f"GAUNTLET DEVSPACE — chat transcript",
        f"Project: {project_name}",
        f"Session: {short}",
        "",
        "—  J'S CLOSING NOTE  —",
        narrative or "(no narrative)",
        "",
        "—  CONVERSATION  —",
    ]
    for m in messages:
        role = (m.get("role") or "?").upper()
        body = (m.get("content") or "")[:4000]
        text_lines.append(f"[{role}]")
        text_lines.append(body)
        text_lines.append("")

    text = "\n".join(text_lines)

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    msgs_html = []
    role_colors = {
        "user": "#E7ECF5", "assistant": "#00D9FF",
        "agent": "#00D9FF", "system": "#7D8597",
    }
    for m in messages:
        role = (m.get("role") or "?").lower()
        color = role_colors.get(role, "#7D8597")
        body = esc(m.get("content") or "")
        msgs_html.append(
            f'<div style="border-left:2px solid {color};padding:8px 12px;margin:8px 0;'
            f'background:rgba(255,255,255,0.03);">'
            f'<div style="font-family:monospace;font-size:11px;color:{color};'
            f'letter-spacing:0.2em;margin-bottom:4px;">{role.upper()}</div>'
            f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:13px;'
            f'color:#E7ECF5;white-space:pre-wrap;">{body}</div>'
            f'</div>'
        )

    html = (
        '<div style="font-family:ui-monospace,Menlo,monospace;background:#050709;'
        'color:#E7ECF5;padding:24px;max-width:680px;margin:auto;">'
        '<div style="border-bottom:1px solid #00D9FF33;padding-bottom:12px;margin-bottom:16px;">'
        '<div style="font-size:11px;letter-spacing:0.3em;color:#00D9FF;">GAUNTLET DEVSPACE</div>'
        f'<div style="font-size:16px;color:#E7ECF5;margin-top:6px;">{esc(project_name)} · session {short}</div>'
        '</div>'
        '<div style="border:1px solid #00D9FF33;padding:12px;margin-bottom:20px;background:rgba(0,217,255,0.05);">'
        '<div style="font-size:11px;letter-spacing:0.2em;color:#00D9FF;margin-bottom:6px;">J\'S CLOSING NOTE</div>'
        f'<div style="white-space:pre-wrap;color:#E7ECF5;">{esc(narrative or "(no narrative written)")}</div>'
        '</div>'
        '<div style="font-size:11px;letter-spacing:0.2em;color:#7D8597;margin-bottom:8px;">CONVERSATION</div>'
        + "".join(msgs_html) +
        '<div style="border-top:1px solid #00D9FF33;padding-top:12px;margin-top:20px;'
        'font-size:10px;color:#7D8597;">Sent because you opted in to transcript emails. '
        'Disable in Settings → Email transcripts.</div>'
        '</div>'
    )
    return html, text
