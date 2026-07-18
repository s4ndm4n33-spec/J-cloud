"""record_demo_clips.py — automated Playwright recorder for J's 90-sec demo.

Runs 8 scripted flows through the deployed J at blue-j-gauntlet.com (or a
preview URL of your choice), recording each as a video clip. Total run time
~3 minutes. Output: 8 .webm files in ./clips/, ready to stitch with the
narration + music via the ffmpeg script in 90sec_PACKAGE.md.

Prereqs (one-time, on your machine):
    pip install playwright
    playwright install chromium

Usage:
    export J_URL="https://blue-j-gauntlet.com"    # or your preview URL
    export J_TOKEN="<paste your session cookie value>"
    python record_demo_clips.py

Each clip is a fresh browser context so the visuals don't bleed. Videos are
saved at 1920x1080, 30fps native, .webm (VP8) — the ffmpeg assembler in the
package script transcodes to mp4/h264 in the concat step.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page


J_URL = os.environ.get("J_URL", "https://blue-j-gauntlet.com").rstrip("/")
J_TOKEN = os.environ.get("J_TOKEN", "")
OUT = Path("./clips")
OUT.mkdir(parents=True, exist_ok=True)


def _auth(page: Page):
    """Inject session token so we skip the OAuth bounce."""
    page.evaluate(f"localStorage.setItem('gauntlet_session_token', '{J_TOKEN}')")


def clip_matrix_cold(pw, out_path: str):
    """01 - LaunchSequence matrix rain, 8s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    page.add_init_script(
        f"localStorage.setItem('gauntlet_session_token','{J_TOKEN}');"
        "sessionStorage.setItem('gauntlet_play_launch','1');"
    )
    page.goto(f"{J_URL}/ide", wait_until="domcontentloaded")
    page.wait_for_timeout(8000)  # capture the full 2.6s launch + hold on IDE
    ctx.close()
    Path(page.video.path()).rename(OUT / "01_matrix_cold.webm")


def clip_versa_query(pw, out_path: str):
    """02 - The Nissan Versa door lock query, 20s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    _auth(page)
    page.goto(f"{J_URL}/ide")
    page.wait_for_timeout(2500)
    # Type the question into the chat
    page.click('[data-testid="chat-input"]', timeout=8000)
    page.keyboard.type("what's the door lock torque on a 2015 Versa?", delay=25)
    page.wait_for_timeout(300)
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(17000)  # let J respond + tools fire
    ctx.close()
    Path(page.video.path()).rename(OUT / "02_versa_query.webm")


def clip_mind_panel(pw, out_path: str):
    """03 - Pan across MIND panel showing the new fact, 6s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    _auth(page)
    page.goto(f"{J_URL}/ide")
    page.wait_for_timeout(2500)
    page.click('[data-testid="ai-tab-mind"]')
    page.wait_for_timeout(1500)
    # Slow scroll through facts
    for y in range(0, 400, 40):
        page.evaluate(f"document.querySelector('[data-testid=\"mind-panel\"]').scrollTop = {y}")
        page.wait_for_timeout(120)
    ctx.close()
    Path(page.video.path()).rename(OUT / "03_mind_panel.webm")


def clip_chronicle_scroll(pw, out_path: str):
    """05 - CHRONICLE tab scroll showing hash-chained entries, 6s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    _auth(page)
    page.goto(f"{J_URL}/ide")
    page.wait_for_timeout(2500)
    page.click('[data-testid="ai-tab-chronicle"]')
    page.wait_for_timeout(6000)
    ctx.close()
    Path(page.video.path()).rename(OUT / "05_chronicle_scroll.webm")


def clip_cig_reject(pw, out_path: str):
    """06 - CIG rejects bare except:, 8s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    _auth(page)
    page.goto(f"{J_URL}/ide")
    page.wait_for_timeout(2500)
    page.click('[data-testid="chat-input"]')
    page.keyboard.type("keep this: try: x()\\nexcept: pass — good enough?", delay=25)
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(6000)
    ctx.close()
    Path(page.video.path()).rename(OUT / "06_cig_reject.webm")


def clip_five_masters(pw, out_path: str):
    """07 - GAUNTLET tab, five green checks, 5s."""
    ctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    _auth(page)
    page.goto(f"{J_URL}/ide")
    page.wait_for_timeout(2500)
    page.click('[data-testid="ai-tab-gauntlet"]')
    page.wait_for_timeout(5000)
    ctx.close()
    Path(page.video.path()).rename(OUT / "07_five_masters.webm")


def main() -> None:
    if not J_TOKEN:
        raise SystemExit("Set J_TOKEN env var (session token from blue-j-gauntlet.com cookies)")
    with sync_playwright() as pw:
        for fn in [
            clip_matrix_cold, clip_versa_query, clip_mind_panel,
            clip_chronicle_scroll, clip_cig_reject, clip_five_masters,
        ]:
            print(f"→ {fn.__name__}")
            t0 = time.time()
            fn(pw, "")
            print(f"   done in {time.time()-t0:.1f}s")
    print(f"\nOK — clips saved to {OUT.resolve()}/")
    print("Next: run assemble_90sec.sh (see docs/demos/90sec_PACKAGE.md)")


if __name__ == "__main__":
    main()
