# Bubble.io Handoff Package — J Training Console

**Goal:** hand this package to Bubble.io (via Bubble AI or a human builder) and receive back a **finished, deployed training platform** that lets the owner train and evaluate fine-tuned models from their Gauntlet DevSpace chronicle data.

## What's in this package

| File | For whom | What it does |
|---|---|---|
| **`PROMPT.md`** | Bubble AI (paste this in) | The hero product spec. Describes the finished app in one document. |
| **`API_CONTRACT.md`** | Bubble builder + backend dev | REST endpoints Bubble calls. Request/response shapes with examples. |
| **`DATA_MODEL.md`** | Bubble builder | The Bubble Data Types to create — mirrors backend but simplified. |
| **`UI_SPEC.md`** | Bubble builder | Every page, element, and interaction. Data-test-ids for QA. |
| **`WORKFLOWS.md`** | Bubble builder | Bubble Workflow definitions — trigger → action chain. |
| **`DESIGN.md`** | Bubble builder | Color / font / spacing tokens that match Gauntlet DevSpace. |
| **`BACKEND_STUBS.md`** | Emergent backend dev (you) | Endpoints our FastAPI must expose for Bubble to consume. |
| **`HANDOFF.md`** | This file | Meta-doc, start here. |

## How to use it

### If you're using Bubble AI:
1. Open Bubble → new app → "Build with AI"
2. Paste **`PROMPT.md`** as the primary spec
3. Attach the remaining `.md` files as reference documents (Bubble AI supports doc upload)
4. Let it scaffold. Expect ~70% of the UI to auto-generate correctly.
5. Manually configure the API Connector plugin using **`API_CONTRACT.md`**
6. Manually wire the Data Types using **`DATA_MODEL.md`**
7. Verify workflows against **`WORKFLOWS.md`**

### If you're using a human Bubble builder:
1. Send them the whole `/app/docs/bubble/` folder as a zip
2. Ask them to read `HANDOFF.md` → `PROMPT.md` → then dive into whichever reference doc matches their current build step
3. Estimate: **20–40 hours** for a Bubble-native builder to ship this. Free-tier constraints add ~10% overhead.

## Free tier feasibility

**Yes, this fits Bubble's free tier**, with these constraints acknowledged:
- App is served from `your-app-name.bubbleapps.io` (no custom domain until Starter plan)
- Workflow runs capped at ~200/day — fine for owner-only usage
- Database rows: 100 MB total — plenty for training runs metadata (actual JSONL stays on our S3/R2)
- No custom code editor — all logic via visual workflows + API Connector
- API Connector plugin is free and unlimited

**What Bubble physically cannot do (offloaded to backend / Modal):**
- Run training code (no GPU, no Python)
- Store datasets (>100 MB) — kept on S3/R2, Bubble stores only the URL + metadata
- Stream SSE — Bubble polls every 3-5 s during active runs instead
- WebSocket real-time updates — same, polling instead

## Architecture at a glance

```
┌────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Bubble.io (this package builds this)                          │
│     · Auth (owner bearer token)                                 │
│     · Dashboard / Datasets / Runs / Models / Eval / Settings    │
│     · Polls backend every 3-5s during active runs               │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │  REST (API_CONTRACT.md)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Emergent FastAPI backend (BACKEND_STUBS.md — to be built)     │
│     · /api/training/datasets  (export SFT/DPO JSONL → S3)       │
│     · /api/training/runs      (dispatch → track → return)       │
│     · /api/training/models    (registry + promote/rollback)     │
│     · /api/training/eval      (run golden set on any adapter)   │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │  triggers via webhook / SDK
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Modal.com (or Runpod / local rig — swappable)                 │
│     · axolotl LoRA fine-tune on Qwen2.5-7B / Llama-3.1-8B       │
│     · Stores adapter to S3/R2                                   │
│     · POSTs back completion webhook                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## What to send back to Emergent after Bubble ships

1. The Bubble app URL (`your-app.bubbleapps.io`)
2. The API Connector calls you actually wired (they may differ slightly from the spec)
3. Screenshots of every page
4. Any spec ambiguities you had to resolve — so we can fold the answer back into `PROMPT.md`

Then Emergent wires up the backend endpoints in `BACKEND_STUBS.md` and the whole loop lights up.
