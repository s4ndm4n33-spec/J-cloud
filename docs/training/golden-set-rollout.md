# Golden Set Rollout — Three Paste-in Prompts

**Source of truth:** `/app/memory/E_MIND_GOLDEN.json` (v1.0.0, 12 entries)

**Served by:** `GET /api/training/golden-set` (owner-only, 4 formats + raw)

- `?format=raw` — the JSON as authored (default)
- `?format=sft` — generic `{"prompt","completion"}` JSONL — HuggingFace, Axolotl, LoRA trainers
- `?format=openai` — OpenAI fine-tune `{"messages":[…]}` JSONL — the OpenAI files API expects this exact shape
- `?format=anthropic` — Anthropic HH format
- `?format=ollama_ft` — `{"instruction","input","output"}` JSONL — usable for creating a Modelfile SFT bake on the metal
- `?format=dpo` — pair skeleton (chosen filled, rejected stubbed until v1.1)

Optional filter: `&category=success_interlock | failure_vector | ffp_protocol`

Refresh (re-read from disk after editing): `POST /api/training/golden-set/refresh` → returns counts.

---

## PROMPT 1 — for **bolt.new** (Training Console frontend)

Paste this whole block into your bolt.new Training Console project as a follow-up:

```
Add a "Seed Sets" section to the Training Console home page, above the
existing "Prod Datasets" section. This new section pulls the E_MIND_GOLDEN
dataset from the backend and exposes one-click downloads in every trainer
format we support.

## Endpoints to wire

- POST {{apiBaseUrl}}/api/training/golden-set/refresh
    Owner-only. Returns:
    { ok, path, version, entries, by_category, gaps_declared }

- GET  {{apiBaseUrl}}/api/training/golden-set?format=<fmt>&category=<cat>
    Owner-only. Formats: raw | sft | openai | anthropic | ollama_ft | dpo.
    Categories (optional filter): success_interlock | failure_vector | ffp_protocol.
    Returns JSONL for every format except raw (which returns application/json).

## UI

Below the existing health pills, render a fixed card:

  ┌───────────────────────────────────────────────────────────┐
  │  SEED SET · E_MIND_GOLDEN v1.0.0                          │
  │  12 entries — success_interlock: 8  failure_vector: 3     │
  │                ffp_protocol: 1     gaps: 3                │
  │                                                           │
  │  Download:  [RAW] [SFT] [OPENAI] [ANTHROPIC] [OLLAMA_FT]  │
  │  Filter:    ( ) all  ( ) success  ( ) failure  ( ) ffp    │
  │  [REFRESH]                                                │
  └───────────────────────────────────────────────────────────┘

Every download button hits the endpoint with the current format + filter
and streams the response into a file with a name of the shape:
  E_MIND_GOLDEN_v1.0.0_<format>_<filter>_<YYYYMMDD>.jsonl

On mount, call /refresh once to populate the counts. On REFRESH click,
call again. On any 4xx/5xx, surface the detail inline in the card
(never a toast — this section is safety-critical).

## Don't

- Don't cache the endpoint response client-side. The file changes as new
  entries are distilled; every download should be fresh from disk.
- Don't add a "run training" button in this section. Downloads only.
  Training is triggered elsewhere (Prod Datasets section) or by external
  tools consuming these files.
```

---

## PROMPT 2 — for **J on the metal** (Modelfile SFT bake)

If you want J:latest to inherit E1's reasoning shape locally, use the
`ollama_ft` export as a bake input. Paste this into a shell on the metal:

```bash
# 1. Fetch the golden set in ollama-friendly JSONL
curl -s -H "Cookie: session_token=YOUR_OWNER_SESSION" \
     "https://blue-j-gauntlet.com/api/training/golden-set?format=ollama_ft" \
     > ~/E_MIND_GOLDEN.jsonl

# 2. Verify count matches the backend's report
wc -l ~/E_MIND_GOLDEN.jsonl   # should print 12

# 3. Bake into a J.SFT Modelfile that layers on top of the existing J.
#    (This is a *lightweight* in-context bake, not a full LoRA — it just
#    seeds J's default responses with the golden reasoning shape.)
cat > ~/J-golden.Modelfile <<'EOF'
FROM J:latest

# Layer the golden reasoning shape into the SYSTEM prompt so any prompt
# that lacks explicit instructions still elicits Problem/Fix/Why/Next-step
# output with signed receipts.
SYSTEM """You are J, the sovereign coworker of Gauntlet DevSpace.
Every reply follows Problem/Fix/Why/Next-step when the task warrants it.
Cite receipts, not opinions. Prefer deterministic code over LLM narration
when the operator asks for provenance. Falsification-First Principles:
state a hypothesis, run the cheapest orthogonal probes that could refute it,
declare FALSIFIED or CONFIRMED before proposing any fix."""

PARAMETER num_ctx 8192
PARAMETER num_predict 512
PARAMETER stop "<|im_end|>"
EOF

# 4. Create the bake
ollama create J:golden -f ~/J-golden.Modelfile

# 5. Verify — should still respond fast with the new shape
ollama run J:golden "What's your reply shape when I ask you to fix a bug?"
```

For a **real LoRA** fine-tune (not just a Modelfile bake), pull the `sft`
format instead and feed it to Modal via the existing training pipeline:

```bash
curl -s -H "Cookie: session_token=YOUR_OWNER_SESSION" \
     "https://blue-j-gauntlet.com/api/training/golden-set?format=sft" \
     > /tmp/golden.jsonl
# then hit POST /api/training/runs with the file as a seed dataset
```

---

## PROMPT 3 — for **any external trainer** (OpenAI, Together, Anyscale, HuggingFace)

You can now train **any model** — not just J — off the same golden set.
This is the "train E1 herself" path.

### OpenAI fine-tune (GPT-5.x)

```bash
# 1. Pull the golden set in OpenAI's expected messages format
curl -s -H "Cookie: session_token=YOUR_OWNER_SESSION" \
     "https://blue-j-gauntlet.com/api/training/golden-set?format=openai" \
     > E_MIND_GOLDEN_openai.jsonl

# 2. Upload to OpenAI files API
openai files.create --file E_MIND_GOLDEN_openai.jsonl --purpose fine-tune
# → captures file_id: file_abc123

# 3. Launch the fine-tune run
openai fine_tuning.jobs.create \
  --training-file file_abc123 \
  --model gpt-5.4-mini \
  --suffix e1-golden-v1

# 4. When it lands, pin the resulting slug in DevSpace:
#    Settings → OpenAI BYOK → preferred_model: ft:gpt-5.4-mini:you:e1-golden-v1
#    The failover chain will now route OpenAI calls through your fine-tune.
```

### Together AI (any open model — Llama-3.3, Qwen-2.5, Mistral, DeepSeek…)

```bash
curl -s -H "Cookie: session_token=YOUR_OWNER_SESSION" \
     "https://blue-j-gauntlet.com/api/training/golden-set?format=sft" \
     > E_MIND_GOLDEN_sft.jsonl

# Upload via Together's CLI
together files upload E_MIND_GOLDEN_sft.jsonl
# → file-<id>

# Launch fine-tune
together fine-tuning create \
  --training-file file-<id> \
  --model meta-llama/Llama-3.3-70B-Instruct-Reference \
  --lora \
  --n-epochs 3 \
  --suffix e1-golden-v1
```

### HuggingFace / Axolotl / any generic SFT trainer

```bash
curl -s -H "Cookie: session_token=YOUR_OWNER_SESSION" \
     "https://blue-j-gauntlet.com/api/training/golden-set?format=sft" \
     > golden.jsonl
# → 12 rows of {"prompt","completion","meta":{id,category,tags}}
```

Point Axolotl at `golden.jsonl` in the SFT dataset section of its YAML.
Category-filter first if you want a specialist adapter — e.g. train an
adapter on only the FFP protocol entries:

```bash
curl -s "…/api/training/golden-set?format=sft&category=ffp_protocol" -H "$CK" > ffp_only.jsonl
```

---

## What NOT to train on

The three failure-vector entries (`E1_GOLD_006`, `_009`, `_010`) are the
**highest-signal capability** we want the fine-tune to reproduce. Reserve
them as **eval-only holdout** — don't include them in the training file.

Concrete: for any training run, download with `&category=success_interlock`
first, then a separate `&category=ffp_protocol` for the FFP DNA. Keep
`&category=failure_vector` in a separate file that only your eval script
consumes. This is baked into the JSON's `_next_actions_for_training_pipeline`
block if you need to remind yourself later.

---

## Growing the set — v1.1 checklist

To take the golden set from 12 to ~100 entries with real chronicle depth:

1. Set `PROD_MONGO_URL` in preview `.env` so preview's `prod_db` handle
   points at production.
2. Query `prod_db.chronicle_entries.find({actor: "E1", success: true}).limit(200)`.
3. For each entry, ask J to author a golden-set row (Prompt_Intent →
   Reasoning_Path → Signed_Code_Result) — this is the exact task the
   golden set trains E1's descendant to do.
4. Append to `E_MIND_GOLDEN.json` under `entries`, bump the version.
5. `POST /api/training/golden-set/refresh` → confirm new counts.
6. Also fold in the two gaps declared in v1.0.0:
   - A.L.I.C.E. incident → `E1_GOLD_ALICE`
   - 520 errors → `E1_GOLD_520`
