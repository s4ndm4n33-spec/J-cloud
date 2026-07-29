# J LoRA Adapter Serving — Cerebrium

Serves fine-tuned J variants. Loads a base model once per replica, then
applies whichever LoRA adapter you point it at (pulled from Cloudflare R2
where the Modal training pipeline writes them).

## One-time setup

```bash
pip install cerebrium
cerebrium login

# Push secrets so the deployed container can hit R2 / HuggingFace
cerebrium secrets set R2_ACCOUNT_ID          <your R2 account id>
cerebrium secrets set R2_ACCESS_KEY_ID       <your R2 access key>
cerebrium secrets set R2_SECRET_ACCESS_KEY   <your R2 secret>
cerebrium secrets set R2_BUCKET              <your bucket>
cerebrium secrets set HUGGINGFACE_HUB_TOKEN  <hf token — required for Llama>
```

## Deploy

```bash
cd /app/serving/
cerebrium deploy
```

The command prints your endpoint URL, something like:
`https://run.cerebrium.ai/v4/<project-id>/j-lora-serving/predict`

## Call it

```bash
curl -X POST "$CEREBRIUM_ENDPOINT" \
  -H "Authorization: Bearer $CEREBRIUM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt":       "refactor this to use dependency injection",
    "base_model":   "qwen2.5-coder-7b",
    "run_id":       "run_XXXXXX",
    "max_new_tokens": 512,
    "temperature":  0.7,
    "system":       "You are J. Sardonic, capable, kind."
  }'
```

## Response shape

```json
{
  "ok": true,
  "text": "…J's reply…",
  "usage": { "prompt_tokens": 128, "completion_tokens": 342, "total_tokens": 470 },
  "timing_ms": { "load_total_ms": 42.1, "generate_ms": 1183.7 },
  "cache": { "base_loaded": ["qwen2.5-coder-7b"], "adapters_cached": [...] }
}
```

## How adapters flow end-to-end

```
[bolt training console]
        │  POST /api/training/runs
        ▼
[FastAPI backend]  →  [Modal GPU]  →  writes adapter to R2
                                          │
                                          │  s3://{bucket}/adapters/{run_id}/
                                          ▼
[Cerebrium serving pod]  ←  downloads on first request per (base, run_id)
                          ←  caches in-memory (LRU, max 4)
                          →  returns tokens + timing
```

## Hardware sizing

| Model                  | Recommended GPU | Notes                                |
|------------------------|-----------------|--------------------------------------|
| qwen2.5-coder-7b       | AMPERE_A10 24G  | Default in cerebrium.toml            |
| llama-3.1-8b-instruct  | AMPERE_A10 24G  | Requires HUGGINGFACE_HUB_TOKEN        |
| qwen2.5-14b-instruct   | AMPERE_A100_40  | Change `[cerebrium.hardware].gpu`     |

## Wiring into the FastAPI backend

The endpoint URL + token belong in the backend's `.env`:

```
CEREBRIUM_SERVING_URL=https://run.cerebrium.ai/v4/<proj>/j-lora-serving/predict
CEREBRIUM_SERVING_TOKEN=<key>
```

Then a follow-up backend route can dispatch chat turns to a trained
adapter instead of the base LLM chain — the "actually use the fine-tune"
step. That routing layer is deliberately NOT in this repo yet; ship the
serving endpoint first, verify it works, then wire it up.
