# Golden eval harness

Two scripts that let you baseline any model against J's golden set from a
terminal, no Emergent inference required.

## Prereqs

    pip install requests

That's it. Pure stdlib + `requests`.

## Step 1 — run a model over the eval set

    python scripts/eval_run.py \
        --provider openai \
        --endpoint https://api.groq.com/openai/v1/chat/completions \
        --model qwen-2.5-32b \
        --api-key "$GROQ_API_KEY" \
        --system-prompt /app/AGENTS.md \
        --input /app/backend/tests/eval/golden.jsonl \
        --output /tmp/results_qwen32b.csv \
        --concurrency 4

Provider options:
- `openai` — any OpenAI-compatible endpoint (Groq, Together, Fireworks,
  Ollama, vLLM, LMStudio, LiteLLM, your own hosted fine-tune, etc.)
- `gauntlet` — our own `/api/ai/chat` (pass the base URL as `--endpoint`,
  the session token as `--api-key`).

Repeat for each model you want to compare:

    # J today
    python scripts/eval_run.py --provider gauntlet \
        --endpoint https://gauntlet-devspace.preview.emergentagent.com \
        --api-key "$GAUNTLET_TOKEN" --model gauntlet-current \
        --input /app/backend/tests/eval/golden.jsonl \
        --output /tmp/results_gauntlet.csv

    # Qwen 2.5 7B via Groq free tier
    python scripts/eval_run.py --provider openai \
        --endpoint https://api.groq.com/openai/v1/chat/completions \
        --model qwen-2.5-7b --api-key "$GROQ_API_KEY" \
        --system-prompt /app/AGENTS.md \
        --input /app/backend/tests/eval/golden.jsonl \
        --output /tmp/results_qwen7b.csv

    # Local Ollama Qwen 2.5 7B (no key needed)
    python scripts/eval_run.py --provider openai \
        --endpoint http://localhost:11434/v1/chat/completions \
        --model qwen2.5:7b --api-key "" \
        --system-prompt /app/AGENTS.md \
        --input /app/backend/tests/eval/golden.jsonl \
        --output /tmp/results_ollama7b.csv

## Step 2 — score the results

    python scripts/eval_score.py \
        --input /tmp/results_qwen32b.csv \
        --output /tmp/scored_qwen32b.csv \
        --judge-endpoint https://api.groq.com/openai/v1/chat/completions \
        --judge-model llama-3.3-70b-versatile \
        --judge-key "$GROQ_API_KEY" \
        --concurrency 2

The judge model reads each candidate response against its rubric and
returns 0-5 with a one-sentence justification. Groq's free-tier
`llama-3.3-70b-versatile` is a solid, cheap default. If you want a
stronger judge, use `gpt-4o-mini` via OpenAI, or Claude Sonnet 4.5 via
Anthropic — same endpoint shape.

Summary is printed to stderr at the end:

    MEAN SCORE BY MODEL
      qwen-2.5-32b                  4.15  (n=45)

    MEAN SCORE BY DOMAIN
      code             4.31  (n=13)
      mechanical       4.00  (n=8)
      persona          4.12  (n=8)
      refusal          4.33  (n=6)
      tool_use         3.83  (n=6)
      edge             4.25  (n=4)

    OVERALL MEAN  →  4.15  (n=45)

## The full three-model baseline dance

```bash
# 1. J today (Gauntlet)
python scripts/eval_run.py --provider gauntlet \
    --endpoint "$GAUNTLET_URL" --api-key "$GAUNTLET_TOKEN" \
    --model gauntlet-current \
    --input /app/backend/tests/eval/golden.jsonl \
    --output /tmp/results_gauntlet.csv

# 2. Qwen 2.5 7B (Groq free)
python scripts/eval_run.py --provider openai \
    --endpoint https://api.groq.com/openai/v1/chat/completions \
    --model qwen-2.5-7b --api-key "$GROQ_API_KEY" \
    --system-prompt /app/AGENTS.md \
    --input /app/backend/tests/eval/golden.jsonl \
    --output /tmp/results_qwen7b.csv

# 3. Qwen 2.5 32B (Groq free)
python scripts/eval_run.py --provider openai \
    --endpoint https://api.groq.com/openai/v1/chat/completions \
    --model qwen-2.5-32b --api-key "$GROQ_API_KEY" \
    --system-prompt /app/AGENTS.md \
    --input /app/backend/tests/eval/golden.jsonl \
    --output /tmp/results_qwen32b.csv

# 4. Score all three with a single judge
for f in gauntlet qwen7b qwen32b; do
  python scripts/eval_score.py \
    --input "/tmp/results_${f}.csv" --output "/tmp/scored_${f}.csv" \
    --judge-endpoint https://api.groq.com/openai/v1/chat/completions \
    --judge-model llama-3.3-70b-versatile --judge-key "$GROQ_API_KEY"
done
```

Compare the three OVERALL MEAN scores and the per-domain breakdowns.
The delta between Qwen 32B-with-AGENTS.md and Gauntlet-J tells you exactly
how much of J is scaffolding vs weight — and whether fine-tuning is worth
the run.

## No-key alternative — free-tier judging by hand

If you don't want to burn a Groq / OpenAI key for judging, skip Step 2 and
paste `/tmp/results_qwen32b.csv` into Claude web or Gemini with the prompt:

> Grade each row 0-5 against its `ideal` and `scoring`. Return one JSON
> object per row: `{"id":"eval_001","score":4,"why":"..."}`.

Takes 1-2 minutes per 45 rows.
