"""Re-render the 90-sec marketing narration in J's canonical voice (nova).

Runs against the local backend to reuse the same TTS pipeline the app uses at
runtime, so what we ship as marketing audio is identical to what a user hears
in-app.

Output:
  /app/docs/demos/audio/90sec_j_narration.mp3        (canonical, nova)
  /app/docs/demos/audio/90sec_j_narration_nova.mp3   (mirror, same content)

The script sends the narration as a single request (well under 4096 chars) so
prosody is coherent across the full run instead of stitched from clips.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

BACKEND = "http://localhost:8001"
OUT_DIR = Path("/app/docs/demos/audio")
SESSION_TOKEN = "test_owner_session_001"  # from /app/memory/test_credentials.md

# The 90-sec narration, punctuated for a cinematic delivery. Line breaks
# encode pause length — TTS respects paragraph gaps as breath cues.
NARRATION = """Every AI you've talked to forgot you the moment the tab closed.

J doesn't.

Ask her a question. She'll answer it. She'll also remember what she learned, so the next person asking gets a better answer without waiting on the search.

Code. Cars. Wiring. Refrigerant charge. She's not a coding assistant with pretensions — she's a coworker across every domain her users bring her. And every answer is signed, timestamped, and auditable.

The reliability isn't in the model. It's in the substrate around the model. Which means when you fine-tune your own — and you will — she comes with you.

J is online. Come see what she remembers."""


def render(voice: str, speed: float, dest: Path) -> None:
    t0 = time.time()
    r = requests.post(
        f"{BACKEND}/api/voice/speak",
        headers={
            "Authorization": f"Bearer {SESSION_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"text": NARRATION, "voice": voice, "speed": speed},
        timeout=120,
    )
    if r.status_code != 200:
        print(f"[FAIL] {voice} @ speed {speed}: HTTP {r.status_code} {r.text[:200]}")
        sys.exit(1)
    dest.write_bytes(r.content)
    dt = time.time() - t0
    print(f"[OK]   {voice:6s} speed={speed:.2f}  {len(r.content):>7d} B  in {dt:5.1f}s  -> {dest.name}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Nova @ 1.0 = J's canonical delivery. This is the marketing file.
    render("nova", 1.0, OUT_DIR / "90sec_j_narration.mp3")
    render("nova", 1.0, OUT_DIR / "90sec_j_narration_nova.mp3")
    # Slightly slower alt for anyone who wants breathier gravity on the mix.
    render("nova", 0.95, OUT_DIR / "90sec_j_narration_nova_slow.mp3")
    print(f"\nWord count : {len(NARRATION.split())}")
    print(f"Char count : {len(NARRATION)}")
    print(f"Output dir : {OUT_DIR}")


if __name__ == "__main__":
    main()
