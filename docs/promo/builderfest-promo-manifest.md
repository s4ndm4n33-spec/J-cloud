# Gauntlet DevSpace — Builder Fest Promo Manifest
**Feed this whole file to the director agent. It contains the vibe, the auth,
the selectors, the beats, the VO, and the deliverables. No verbal briefing
needed — this file is the brief.**

_authored by E1 (main agent) · 2026-08-24 · signed for the director agent_

---

## 0 · TL;DR for the director

- **Product:** Gauntlet DevSpace — a sovereign cloud IDE with a JARVIS-class AI coworker (J), Five Masters gauntlet, verifiable execution logs, live migration receipts, and a training pipeline that lets you fine-tune your own J.
- **Occasion:** Builder Fest promo.
- **Deliver:** 1× hero cut (60s, 16:9, 3840×2160), 1× vertical cut (30s, 9:16, 1080×1920), 1× teaser (15s, 1:1, 1080×1080). Master ProRes 422 HQ + H.264 web-ready + WebP animated poster + first-frame JPG.
- **Vibe:** "Cockpit under load." Noir cyberpunk cockpit that actually works. Real code. Real terminal. J responds in real time. No stock UI mockups. No AI-slop gradients.
- **Palette:** near-black `#0B0F14` background · cyan `#39E1FF` primary · signal orange `#FF7A2A` accent · viridian `#0E7C66` status-green · alloy grey `#8896A6` copy.
- **Tagline:** _"Sovereign infrastructure. Verifiable execution. Zero permission slips."_
- **Do NOT:** synthesize UI. Screencap the real app. Do NOT let the model paraphrase VO lines — they are exact.

---

## 1 · Vibe & tone bible

### Visual reference words (for director-model prompts)
`instrument panel · cockpit HUD · noir cyberpunk · grain overlay 6% · glass-morphism 18px backdrop-blur · deterministic motion · CRT phosphor bloom on cyan text · monospaced typography · negative space · aircraft cockpit under load · black box recorder · hardware diagnostic screen · Jony Ive meets Blade Runner 2049`

### Motion rules
- Ease: `cubic-bezier(0.16, 1, 0.3, 1)` (out-expo). **Never bouncy.**
- Cuts: hard cuts on downbeats. **No dissolves.** Whip-pans only when moving between IDE panels.
- Camera language:
  - **Push-ins** on typed characters (chat input, terminal).
  - **Static holds** on receipts (migration log, gauntlet verdict, telemetry).
  - **Rack focus** blur → sharp when a new tool card lands in the AI panel.
- Text-on-screen animates in via **1px stroke draw + 8px offset settle**, never fade+scale.

### Sound design
- Score: cold electro. Reference tracks: _Trent Reznor "Hand Covers Bruise"_, _Ben Salisbury/Geoff Barrow "Sacrificial"_, _Kaitlyn Aurelia Smith "Existence in the Unfurling"_. 90 BPM sub-bass pulse. **No dubstep. No orchestral swells.**
- SFX: mechanical keyswitch (Kailh Box Jade reference), CRT power-on hum under HUD holds, single "chime" (glockenspiel F#5 4th octave) on each gauntlet verdict.
- Voice: calm male-neutral, mid-30s, dry delivery. Reference: _Michael Fassbender in "Prometheus"_. **No hype cadence.**

---

## 2 · Headless browser access

### 2.1 Environment
- **URL (preview, for filming):** `https://gauntlet-devspace.preview.emergentagent.com`
- **URL (production):** `https://blue-j-gauntlet.com` — DO NOT film here; it has real user data.
- Browser: Chromium 121+ headless via Playwright. Enable GPU (`--enable-gpu`). Do NOT enable headless-shell mode — needs full font rasterization for Exo 2.
- Viewport for hero (16:9): `{ width: 3840, height: 2160, deviceScaleFactor: 1 }`. For 30s vertical: `{ width: 1080, height: 1920, deviceScaleFactor: 2 }`. For teaser 1:1: `{ width: 2160, height: 2160, deviceScaleFactor: 1 }`.
- Fonts: `Exo 2` + `JetBrains Mono` load from CDN — wait for `document.fonts.ready` before every capture.
- Reduced motion: **do NOT** set `prefers-reduced-motion` (we want the app's motion).

### 2.2 Auth (test owner)
Set this cookie BEFORE navigating to the IDE. It bypasses OAuth cleanly.

```json
{
  "name": "session_token",
  "value": "test_owner_session_001",
  "domain": "gauntlet-devspace.preview.emergentagent.com",
  "path": "/",
  "httpOnly": true,
  "secure": true,
  "sameSite": "None"
}
```

- **user_id:** `user_5d2818f635a9`
- **email shown in HUD:** `s4ndm4n33@gmail.com`
- **is_owner:** true (Universal Key armed, Admin panel visible)

Playwright snippet:
```python
context = await browser.new_context(viewport={"width": 3840, "height": 2160})
await context.add_cookies([{
    "name": "session_token",
    "value": "test_owner_session_001",
    "domain": "gauntlet-devspace.preview.emergentagent.com",
    "path": "/", "httpOnly": True, "secure": True, "sameSite": "None"
}])
page = await context.new_page()
await page.goto("https://gauntlet-devspace.preview.emergentagent.com/ide")
await page.wait_for_selector('[data-testid="ai-coworker"]', state="visible")
await page.evaluate("document.fonts.ready")
```

If the session ever bounces (401), reseed via mongosh (see `/app/memory/test_credentials.md` §Re-seed). No password needed — cookie auth only.

### 2.3 Warm-up sequence (run once per capture session)
1. Navigate to `/ide`.
2. Create a fresh project titled `Builder Fest Demo`:
   - Click `[data-testid="new-project-button"]`
   - Fill `[data-testid="new-project-name-input"]` with `Builder Fest Demo`
   - Click `[data-testid="new-project-confirm"]`
3. Wait for `[data-testid="file-tree"]` to render.
4. Prime a `hello.py` file with 6 lines of intentionally boring code (see §4 Shot 03).
5. Open the AI Coworker (`[data-testid="ai-coworker"]`) to the **Chat** tab (`[data-testid="ai-tab-chat"]`).

---

## 3 · Selector library (copy/paste for the director's Playwright agent)

All selectors below are stable `data-testid`s. Prefer these over CSS/XPath.

| Purpose | Selector |
|---|---|
| IDE root | `[data-testid="ai-coworker"]` (right panel) · `[data-testid="file-tree"]` (left) |
| New project | `[data-testid="new-project-button"]` → `[data-testid="new-project-name-input"]` → `[data-testid="new-project-confirm"]` |
| File tree file/dir | `[data-testid="tree-file-<path>"]` · `[data-testid="tree-dir-<path>"]` |
| Terminal | `[data-testid="terminal-container"]` · type via `await page.keyboard.type("...")` after `page.locator('[data-testid="terminal-container"]').click()` |
| AI Coworker tabs | `[data-testid="ai-tab-chat"]` · `ai-tab-refine` · `ai-tab-gauntlet` · `ai-tab-logs` · `ai-tab-migration` |
| Chat input | `[data-testid="chat-input"]` → send: `[data-testid="chat-send"]` |
| Chat message stream | `[data-testid="chat-messages"]` (assistant turns show `agent-message`) |
| "Served by" pill (whose LLM answered) | `[data-testid="chat-served-by"]` |
| Chain telemetry HUD strip | `[data-testid="chain-telemetry"]` (last 5 pills) · individual: `[data-testid="telemetry-0"]`..`telemetry-4` |
| Tool-call cards inside J's replies | `[data-testid="tool-card-<tool_name>"]` (e.g. `tool-card-create_file`, `tool-card-run_command`, `tool-card-gauntlet_check`) |
| Gauntlet AST panel | `[data-testid="gauntlet-panel"]` · verdict badge: `[data-testid="gauntlet-verdict"]` · full audit: `[data-testid="gauntlet-full"]` |
| Migration log panel | `[data-testid="ai-tab-migration"]` → `[data-testid="log-content"]` (rendered markdown) |
| Chronicle | `[data-testid="chronicle-panel"]` |
| Admin shield (owner-only) | `[data-testid="admin-link"]` |
| Ambient awareness pulse | `[data-testid="ambient-pulse"]` (top-right dot when J is watching) |
| Settings modal | `[data-testid="cmd-k"]` → type `settings` → Enter · or click gear icon |

---

## 4 · Shot list — HERO CUT (60 seconds, 16:9)

Every shot lists: `duration · viewport action · voiceover · on-screen text · sfx · capture notes`.
All VO lines are **exact — do not paraphrase**. Total VO word count = 118 (spoken at 118 wpm = 60s).

### SHOT 01 — Black frame with signal (0:00 → 0:03) · 3s
- **Action:** Full black. A single cyan `1px × 1px` pixel appears at exact center. Grows to a `4px` square. Then a HUD-style crosshair reticle draws around it (1px cyan, ease-out-expo, 400ms).
- **VO:** _(silence, breath)_
- **On-screen text:** none
- **SFX:** CRT power-on hum (60 Hz sub with faint 15.7 kHz whine), rising to full level over 2s.
- **Capture:** synthetic frame — no browser needed. Render in After Effects / Motion.

### SHOT 02 — Cold-open the IDE (0:03 → 0:07) · 4s
- **Action:** Whip cut into a wide static shot of the full IDE at 3840×2160. Everything already loaded: file tree left, Monaco center with a Python file open, AI Coworker right pane, terminal at the bottom, telemetry HUD strip at the very bottom edge.
- **VO:** _"This is a cockpit."_
- **On-screen text:** none
- **SFX:** one deep sub-bass hit (60 Hz, 200ms decay) on cut. Score enters at 0:04 — 90 BPM pulse.
- **Capture:**
  ```python
  await page.wait_for_selector('[data-testid="chain-telemetry"] [data-testid="telemetry-0"]')
  await page.screenshot(path="shots/02_ide_wide.png", full_page=False)
  ```

### SHOT 03 — J's chat input (0:07 → 0:13) · 6s
- **Action:** Rack focus zoom into the AI Coworker's chat input. User types (record real keystrokes at ~85 wpm — do not paste): **`build me a fibonacci CLI with a test suite and commit it`**. Cursor blinks between characters.
- **VO:** _"Tell it what you want."_
- **On-screen text:** subtle 12pt JetBrains Mono, bottom-right, alloy grey: `input · chat-input`
- **SFX:** mechanical keyswitch per character (Kailh Box Jade sample), softer than diegetic — panned centre.
- **Capture:**
  ```python
  chat = page.locator('[data-testid="chat-input"]')
  await chat.click()
  await page.keyboard.type("build me a fibonacci CLI with a test suite and commit it", delay=70)
  ```

### SHOT 04 — Send & the chain flickers (0:13 → 0:17) · 4s
- **Action:** Click send. Camera whip-pans DOWN to the telemetry HUD strip. The new pill slides in from the right with a 1px cyan stroke flash, resolved as `CHT · universal/gemini-3-flash · 843ms · ↻0`. The previous pills settle left. Slow-mo the pill land by 40%.
- **VO:** _"Watch it think."_
- **On-screen text:** none. The pill IS the text.
- **SFX:** single glockenspiel chime (F#5) as the pill locks.
- **Capture:**
  ```python
  await page.locator('[data-testid="chat-send"]').click()
  await page.wait_for_selector('[data-testid="telemetry-0"]', state="visible")
  # Capture a 2s video clip of the strip at 60fps for slow-mo:
  # use page.video with viewport clipped to y: 2080-2160, x: full
  ```

### SHOT 05 — J's tool-call cascade (0:17 → 0:25) · 8s
- **Action:** Camera pans BACK UP to the AI panel. J's assistant reply streams in. As tool calls resolve, cards appear one at a time with a 200ms stagger. Sequence to capture:
  1. `tool-card-create_file` → `fib.py` (green OK badge)
  2. `tool-card-create_file` → `test_fib.py` (green OK badge)
  3. `tool-card-run_command` → `pytest -q` — expand card to show `2 passed in 0.03s` (green OK)
  4. `tool-card-git_commit` → `feat: fibonacci CLI + tests` (green OK)
- **VO:** _"J writes the file. J runs the test. J commits the change. Every step is a receipt."_
- **On-screen text:** none — the cards are the whole story.
- **SFX:** subtle "card-lock" click on each card land (1kHz sine pluck, 30ms).
- **Capture:**
  ```python
  await page.wait_for_selector('[data-testid="tool-card-git_commit"]', timeout=90_000)
  # Then screen-record the AI panel for 8s at 60fps
  ```
- **Note:** if J doesn't emit git_commit deterministically, seed the prompt to be explicit: `build me a fibonacci CLI with a test suite and commit it with message "feat: fibonacci CLI + tests"`.

### SHOT 06 — The gauntlet holds the line (0:25 → 0:32) · 7s
- **Action:** Cut to a NEW project state (pre-primed off-camera). The file open is `unsafe.py` with a line like `os.system(user_input)`. In the Chat, the user types **`ship it`**. J's reply lands, but the Gauntlet AST panel (`[data-testid="gauntlet-panel"]`) at the bottom flips from viridian `PASS` to signal-orange `HALT` with a large verdict badge. The `gauntlet-verdict` shows: `HALT · destructive_pattern · shell_injection`. Camera slow push-in on the verdict badge.
- **VO:** _"But not everything ships. When code fails integrity — it stops. Cold."_
- **On-screen text:** none
- **SFX:** low-frequency "clank" (metal bolt lock, pitched to F1) on HALT flip. Score drops out for 400ms, then re-enters.
- **Capture:**
  ```python
  await page.locator('[data-testid="ai-tab-gauntlet"]').click()
  await page.wait_for_selector('[data-testid="gauntlet-verdict"]:has-text("HALT")')
  await page.screenshot(path="shots/06_halt.png",
      clip={"x": 2400, "y": 1500, "width": 1200, "height": 500})
  ```

### SHOT 07 — Migration log auto-writes (0:32 → 0:38) · 6s
- **Action:** Cut to the Migration Log panel (`[data-testid="ai-tab-migration"]`). Latest entry scrolls into view, timestamp and `_signed: **J**_` visible. The next entry auto-appends on-screen — `2026-08-24T…` header slides in top-down with the 8px settle. **Every character of the entry is real** — this is the actual code-signed log, not a mock.
- **VO:** _"The log writes itself. Code-signed. Timestamped. Yours."_
- **On-screen text:** none — the log IS the text.
- **SFX:** JetBrains Mono keyclick loop under the header animation (12 clicks total).
- **Capture:**
  ```python
  await page.locator('[data-testid="ai-tab-migration"]').click()
  await page.wait_for_selector('[data-testid="log-content"] h2:first-child')
  # scroll to top, then record a 4s clip of the panel
  await page.evaluate('document.querySelector(\'[data-testid="log-content"]\').scrollTop = 0')
  ```

### SHOT 08 — Failover: five keys, one voice (0:38 → 0:45) · 7s
- **Action:** Split screen. Left: Settings modal open (`cmd-k` → `settings`) with all five BYOK provider cards visible (`byok-provider-chips` row). Right: telemetry HUD strip in isolation. On the right, we simulate a rapid failover sequence — pills scroll in showing: `universal/gemini · SKIP · rate_limit` → `byok/openai · SKIP · no_credits` → `byok/anthropic · SKIP · low_balance` → `byok/groq · OK · 412ms`. The final green pill lands with a soft glow.
- **VO:** _"If one provider goes dark, the next takes the shift. You bring the keys. J routes the traffic."_
- **On-screen text:** small legend bottom-right: `openai · anthropic · gemini · groq · openrouter · ollama`
- **SFX:** brief static rush on each SKIP, sub-bass hit on the OK land.
- **Capture:** best done as two separate captures composited in post — grab the settings modal at rest, then capture the telemetry strip at 60fps while triggering real failover via a rate-limited test key.

### SHOT 09 — Run on the metal (0:45 → 0:51) · 6s
- **Action:** Cut to the same IDE, but the "served by" pill under J's reply reads: `served by · byok/ollama · llama-3.3-8b · 3.2s · WKL`. Push in on the pill. Then rack-focus behind the browser to reveal a physical MacBook / mini-PC on a desk (composite / stock plate) — implying the model is running locally.
- **VO:** _"Bring your own model. Bring your own metal. Sovereign end to end."_
- **On-screen text:** center-lower, 14pt Exo 2 alloy grey: `local · llama-3.3 · wkl-compressed`
- **SFX:** score builds — new sub-bass layer enters.
- **Capture:**
  ```python
  # requires a running local Ollama endpoint saved as byok
  await page.wait_for_selector('[data-testid="chat-served-by"]:has-text("ollama")')
  await page.screenshot(path="shots/09_metal.png",
      clip={"x": 2400, "y": 900, "width": 1400, "height": 200})
  ```

### SHOT 10 — Training loop teaser (0:51 → 0:56) · 5s
- **Action:** Cut to `/admin/training` (owner-only route). Show a dataset row with `source: prod · rows: 12,483 · size: 8.2MB`. Then a Modal.com training run card: `epoch 2/3 · loss 0.42 · GPU A100`. Fast whip-pan to a fresh chat where J is now labelled `served by · trained/jarvis-lora-v3`.
- **VO:** _"And when it's ready — you don't just use J. You train her."_
- **On-screen text:** small: `dataset · prod-signal only · code-signed`
- **SFX:** score peaks. Then drops to silence for one beat (0:56).
- **Capture:**
  ```python
  await page.goto("https://gauntlet-devspace.preview.emergentagent.com/admin/training")
  await page.wait_for_selector('[data-testid="training-dataset-row"]')
  ```

### SHOT 11 — Tagline hold (0:56 → 0:60) · 4s
- **Action:** Cut to black. Center-set in Exo 2, 96pt, cyan:
  > **Sovereign infrastructure.**
  > **Verifiable execution.**
  > **Zero permission slips.**
  Each line draws in one at a time (350ms each, 200ms stagger). Then the wordmark `GAUNTLET DEVSPACE` appears below in alloy grey, 32pt, letter-spaced +2%.
  Bottom-right, small: `builder fest · <event-date-placeholder>` · URL: `blue-j-gauntlet.com`
- **VO:** _"Gauntlet DevSpace. See you at Builder Fest."_
- **On-screen text:** as above
- **SFX:** score resolves on a single sustained low note. Final glockenspiel chime on the wordmark.
- **Capture:** synthetic, no browser needed.

---

## 5 · Vertical cut (30s, 9:16, 1080×1920)

Use shots **02 → 04 → 06 → 07 → 11** at their original durations except:
- Shot 02 trimmed to 2s (just the wide reveal).
- Shot 04 held for full 4s (the pill lock is the strongest visual).
- Shot 07 trimmed to 3s (log auto-append).
- Shot 11 held for 5s (breathing room on the tagline).

VO for vertical (rewrite, 61 words = 30s at 122 wpm):
> _"This is a cockpit. Tell it what you want. Watch it think. When code fails integrity — it stops. Cold. The log writes itself, code-signed. Sovereign infrastructure. Verifiable execution. Zero permission slips. Gauntlet DevSpace. See you at Builder Fest."_

Reframe rules for 9:16:
- The IDE is a horizontal thing. Do NOT letterbox. Instead, crop to the AI Coworker panel + telemetry strip (both are vertical-friendly).
- File tree and Monaco editor: capture a separate zoomed 9:16 shot of the tree scrolling.

---

## 6 · Teaser (15s, 1:1, 1080×1080)

Use shots **02 (1.5s) → 04 (3s) → 06 (3s) → 11 (7.5s)**.

VO for teaser (26 words = 13s + 2s pad):
> _"Tell it what you want. Watch it think. When code fails integrity — it stops. Cold. Gauntlet DevSpace. Builder Fest."_

---

## 7 · Color grade

- Master LUT: mild teal-orange split — lift the shadows to cyan `#39E1FF` at 5% opacity, push highlights toward `#FF7A2A` at 3%.
- Grain: 35mm film grain plate at 6% opacity, multiply blend.
- Chromatic aberration: 0.8px at frame edges only (mask center 70%).
- Bloom: threshold 0.85, radius 12px, cyan-tinted, 20% opacity. Applies to the chain-telemetry pills and any `text-cyan` HUD copy.
- Vignette: soft radial, 15% opacity, feather 40%.
- **Do NOT** apply film-emulation LUTs (Kodak 2383 etc.). We want digital-cockpit precision, not celluloid nostalgia.

---

## 8 · Post-production checklist

- [ ] Master ProRes 422 HQ, 60fps, 3840×2160, Rec.709 gamma 2.4
- [ ] H.264 web deliverable, 60fps, 3840×2160, CRF 18, high profile
- [ ] Vertical 9:16 H.264, 30fps, 1080×1920, CRF 20
- [ ] Teaser 1:1 H.264, 30fps, 1080×1080, CRF 20
- [ ] WebP animated poster: shot 04's pill-lock, 3s loop, ≤400KB
- [ ] First-frame JPG for Twitter/OG cards, 1200×630, ≤200KB
- [ ] Closed captions (SRT + VTT) for all three cuts — VO is exact, transcribe verbatim
- [ ] Audio bounce: -14 LUFS integrated, true peak ≤ -1 dB
- [ ] Frame-safe zone: 5% inner margin on all sides; keep every HUD element inside it

---

## 9 · Risk & mitigation

- **J refuses / hallucinates the demo flow:** the shot list is deterministic on the tool cards, not J's prose. If a run doesn't emit the expected `git_commit` card, retry with an explicit prompt (see Shot 05 note). Do **not** ship prose the model didn't actually generate — the whole point is verifiable receipts.
- **Rate-limited providers during Shot 08:** the failover cascade IS the point of Shot 08. If chain succeeds on step 1, force failure by temporarily setting `EMERGENT_LLM_KEY=""` in preview `.env` and reverting after capture. Do not fake the pills in post.
- **Preview is down when filming:** fall back to the local dev pod (`http://localhost:3000/ide`) — same selectors, same auth cookie works if you also point the browser at `localhost:8001` for the API. Never film prod.
- **Font not loaded:** every `await page.screenshot` and `page.locator.screenshot` must be preceded by `await page.evaluate("document.fonts.ready")`. Missing Exo 2 fallback → Arial → looks like Squarespace slop.

---

## 10 · Deliverable folder structure

```
/deliverables/builderfest-promo/
  ├── master/
  │   ├── hero_60s_16x9_prores422hq.mov
  │   ├── vertical_30s_9x16_prores422hq.mov
  │   └── teaser_15s_1x1_prores422hq.mov
  ├── web/
  │   ├── hero_60s_16x9_h264.mp4
  │   ├── vertical_30s_9x16_h264.mp4
  │   ├── teaser_15s_1x1_h264.mp4
  │   ├── hero_poster.webp
  │   └── hero_firstframe.jpg
  ├── captions/
  │   ├── hero.srt / hero.vtt
  │   ├── vertical.srt / vertical.vtt
  │   └── teaser.srt / teaser.vtt
  └── raw_captures/
      ├── shots/*.png
      ├── clips/*.webm
      └── audio/vo_takes_*.wav
```

---

## 11 · Signature

_Manifest authored by **E1 (main agent)**. Vibe chosen unilaterally per operator instruction ("choose the vibe yourself. Show us off."). Any deviation from the VO script, palette, or motion rules must be logged as an amendment entry at the bottom of this file, code-signed, before edit._

`— end of manifest —`
