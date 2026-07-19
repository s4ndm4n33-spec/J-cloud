# J DEMO — 90 SECOND CUT — production package

## Assets shipped

- `docs/demos/90sec_script.md` — the script with beat timing
- `docs/demos/audio/90sec_j_narration.mp3` — **J's voice, rendered** (nova via OpenAI TTS through the app's live `/api/voice/speak` pipeline). Duration: **37.7 seconds** of actual speech. **Re-rendered 2026-07-19** as a single-request take (coherent prosody across the full run, not stitched from clips).
- `docs/demos/audio/90sec_j_narration_nova.mp3` — mirror of the canonical file.
- `docs/demos/audio/90sec_j_narration_nova_slow.mp3` — alternate at 0.95× speed (~39.9s) if you want extra gravitas on the mix.
- `docs/demos/audio/90sec_j_narration_onyx_male.mp3` — legacy pre-nova take, kept for reference.
- `docs/demos/render_90sec_audio.py` — the render script. Re-run any time the narration text is edited.

The 38-second narration + ~52s of pre/post/pause = a full 90s runtime. Marketing cuts *breathe* — cold open, cold close, moments where the voice sits back and lets the visual carry. Do not fill the 52s of headroom with more narration; fill it with atmosphere.

---

## Shot list — record these clips in order

Screen-capture at **1920×1080, 30fps** (60fps if your capture card supports it). All clips are ~5-15 seconds. Trim slack in post; assembly script handles pacing.

| # | Clip name | Duration | What to record |
|---|---|---|---|
| 1 | `01_matrix_cold.mp4` | 8s | The LaunchSequence matrix rain on a fresh page load. Let it run 3s before "SOVEREIGN SHARDS" title appears. |
| 2 | `02_versa_query.mp4` | 20s | Fresh IDE. Type into the chat panel: **"what's the door lock torque on a 2015 Versa?"** Let J respond in one shot — you should see `recall_knowledge` fire first, then `web_search`, then the answer. Camera stays on the chat + tools column. |
| 3 | `03_mind_panel.mp4` | 6s | Click the MIND tab. Camera pans across the newly-learned fact. Source URL visible. |
| 4 | `04_split_domains.mp4` | 15s | Open two chat sessions side-by-side (or record two takes and split in post). One asks a Python bug; the other asks about heat-pump refrigerant charge. Both answer in J's voice. |
| 5 | `05_chronicle_scroll.mp4` | 6s | CHRONICLE tab, scroll through the hash-chained entries. Camera focuses on the `signer: J` field and the entry hashes. |
| 6 | `06_cig_reject.mp4` | 8s | In chat, paste `try: something()\nexcept: pass` and ask J to keep it. She should refuse and explain the CIG rejection. |
| 7 | `07_five_masters.mp4` | 5s | GAUNTLET tab. All five green checks visible. Pan across slowly. |
| 8 | `08_qr_card.mp4` | 8s | Static end card. Black bg, QR code (`/app/docs/media/qr/blue-j-gauntlet.png`) with the tagline "**J IS ONLINE**" underneath. |

Total raw footage: ~76s. You'll trim ~10-15% in post to hit exactly 90.

---

## Music picks — 3 options, all royalty-free, all commercial-use-clear

Match the aesthetic (cyan/steel, quiet menace, tech-workshop). All from **Pixabay Music** (CC0/Pixabay license, no attribution required, no strikes).

1. **"Cyberpunk"** by penguinmusic — https://pixabay.com/music/main-title-cyberpunk-2099-9074/ — dark synthwave, JARVIS/Blade Runner adjacent. **Recommended primary.**
2. **"Powerful Cinematic Trailer"** by Sergey Zavgorodniy — https://pixabay.com/music/main-title-powerful-cinematic-trailer-115664/ — orchestral, escalating. Use if you want more "reveal" energy.
3. **"Electronic Cinematic Ambient"** by Riko Nakamura — https://pixabay.com/music/ambient-electronic-cinematic-ambient-176907/ — quieter, more atmospheric. Use if you want J's voice to be the dominant element and the music to sit behind.

Alternative (YouTube Audio Library, also free): search "**Slow Motion**" by Wayne Jones, or "**Lens**" by Ryan Little. Both are cleared.

---

## Assembly — the ffmpeg script

Run this on your machine after you have the 8 clips + downloaded music track. It handles: concatenation of clips, adding J's narration at the right point, adding background music with proper ducking (music drops -8dB whenever J speaks), and final MP4 encode.

Save as `assemble_90sec.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ---- Inputs ---- (adjust paths if yours differ)
CLIPS_DIR="./clips"
NARRATION="./audio/90sec_j_narration.mp3"
MUSIC="./music/cyberpunk_2099.mp3"     # your chosen bg track
OUT="./J_demo_90sec.mp4"

# ---- Concatenate clips ----
# Assumes clips named 01_..09 in the order above
printf "file '%s'\n" "$CLIPS_DIR"/0*_*.mp4 > /tmp/clips.txt
ffmpeg -y -f concat -safe 0 -i /tmp/clips.txt \
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
    -an /tmp/visual.mp4

# ---- Build audio: music at -20dB, narration at 0dB, sidechain duck music
# ---- while narration is playing (fast attack, slow release).
ffmpeg -y \
    -i "$MUSIC" \
    -i "$NARRATION" \
    -filter_complex "
        [0:a]volume=-20dB[bg];
        [1:a]adelay=3000|3000,volume=0dB[voice];
        [bg][voice]sidechaincompress=threshold=0.02:ratio=8:attack=5:release=800[ducked];
        [ducked][voice]amix=inputs=2:duration=first:dropout_transition=2[audio]
    " \
    -map "[audio]" -ac 2 -c:a aac -b:a 192k \
    /tmp/audio.m4a

# ---- Mux visual + audio, trim to exactly 90s ----
ffmpeg -y -i /tmp/visual.mp4 -i /tmp/audio.m4a \
    -c:v copy -c:a copy -shortest -t 90 \
    "$OUT"

echo "OK — $OUT"
```

**What the sidechain compressor does**: as soon as J starts speaking, the music level automatically drops 8dB and stays quiet until she pauses. Then it rises back to normal in 800ms. This is the same technique podcast editors use — it means you never manually keyframe volume, and J is always intelligible over the music.

**The `adelay=3000|3000`** on the narration = a 3-second delay before J starts speaking, so the matrix cold open plays without her voice. Tune this if you re-time the opening.

---

## What I need from you to move to the 3-minute cut

Listen to `90sec_j_narration.mp3` first. Answer just:

**Is J's voice** — pace, tone, cadence, gravity — **what you wanted?**

- If yes: I write the 3-min next (same template, product walkthrough).
- If no: tell me what's off. Slower? Less gravel? Different word choice? A different OpenAI TTS voice (`nova`, `echo`, `alloy`, `fable`, `shimmer`)? One iteration and I re-render.

Feedback on that one file locks the voice for all three cuts. Cheapest possible way to not waste render time on the longer scripts.
