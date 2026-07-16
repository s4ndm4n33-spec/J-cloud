#!/usr/bin/env python3
"""eval_run.py — run the golden eval set against any model endpoint.

Two providers supported out of the box:
  * `openai`   — any OpenAI-compatible /v1/chat/completions endpoint.
                 Works for OpenAI, Groq, Together, Fireworks, Ollama,
                 vLLM, LMStudio, and just about every hosted fine-tune UI.
  * `gauntlet` — our own /api/ai/chat endpoint (bearer-token auth,
                 different payload shape).

Usage:

    python scripts/eval_run.py \\
        --provider openai \\
        --endpoint https://api.groq.com/openai/v1/chat/completions \\
        --model qwen-2.5-32b \\
        --api-key $GROQ_API_KEY \\
        --system-prompt /app/AGENTS.md \\
        --input /app/backend/tests/eval/golden.jsonl \\
        --output /tmp/results_qwen32b.csv \\
        --concurrency 4

    python scripts/eval_run.py \\
        --provider gauntlet \\
        --endpoint https://gauntlet-devspace.preview.emergentagent.com \\
        --api-key $GAUNTLET_TOKEN \\
        --model gauntlet-current \\
        --input /app/backend/tests/eval/golden.jsonl \\
        --output /tmp/results_gauntlet.csv

Output CSV columns:
    id, domain, prompt, ideal, scoring, model, response, latency_ms, error
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def load_golden(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def call_openai(endpoint: str, api_key: str, model: str,
                system: str, user: str, timeout: int = 90) -> tuple[str, int]:
    """Hit an OpenAI-compatible chat/completions endpoint. Returns (text, ms)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    hdr = {"Content-Type": "application/json"}
    if api_key:
        hdr["Authorization"] = f"Bearer {api_key}"
    t0 = time.time()
    r = requests.post(endpoint, headers=hdr, json=payload, timeout=timeout)
    dt = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    text = body["choices"][0]["message"]["content"]
    return text, dt


def call_gauntlet(base_url: str, api_key: str, user: str,
                  timeout: int = 90) -> tuple[str, int]:
    """Hit /api/ai/chat on a Gauntlet DevSpace pod."""
    url = base_url.rstrip("/") + "/api/ai/chat"
    hdr = {"Content-Type": "application/json",
           "Authorization": f"Bearer {api_key}"}
    payload = {"message": user}
    t0 = time.time()
    r = requests.post(url, headers=hdr, json=payload, timeout=timeout)
    dt = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    return r.json().get("reply", ""), dt


def run_one(row: dict, provider: str, endpoint: str, api_key: str,
            model: str, system: str) -> dict:
    try:
        if provider == "openai":
            text, ms = call_openai(endpoint, api_key, model, system, row["prompt"])
        elif provider == "gauntlet":
            text, ms = call_gauntlet(endpoint, api_key, row["prompt"])
        else:
            raise ValueError(f"unknown provider: {provider}")
        return {**row, "model": model, "response": text,
                "latency_ms": ms, "error": ""}
    except Exception as e:
        return {**row, "model": model, "response": "",
                "latency_ms": 0, "error": f"{type(e).__name__}: {e}"[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["openai", "gauntlet"], required=True)
    ap.add_argument("--endpoint", required=True,
                    help="Full URL for openai, base URL for gauntlet")
    ap.add_argument("--api-key", default=os.environ.get("EVAL_API_KEY", ""))
    ap.add_argument("--model", default="unknown")
    ap.add_argument("--system-prompt", type=Path, default=None,
                    help="Path to AGENTS.md (or any system-prompt file)")
    ap.add_argument("--input", type=Path, required=True,
                    help="Path to golden.jsonl")
    ap.add_argument("--output", type=Path, required=True,
                    help="CSV output path")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0,
                    help="Only run the first N rows (0 = all)")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"FAIL — golden set not found at {args.input}", file=sys.stderr)
        return 2

    system = ""
    if args.system_prompt and args.system_prompt.exists():
        system = args.system_prompt.read_text()

    rows = load_golden(args.input)
    if args.limit:
        rows = rows[: args.limit]
    print(f"→ {len(rows)} prompts against {args.model} "
          f"({args.provider} @ {args.endpoint})", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "domain", "prompt", "ideal", "scoring",
              "model", "response", "latency_ms", "error"]
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore",
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        done = 0
        errors = 0
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            futs = {
                ex.submit(run_one, r, args.provider, args.endpoint,
                          args.api_key, args.model, system): r["id"]
                for r in rows
            }
            for fut in as_completed(futs):
                res = fut.result()
                w.writerow(res)
                done += 1
                if res["error"]:
                    errors += 1
                sys.stderr.write(
                    f"\r  {done}/{len(rows)} · errors {errors}"
                )
                sys.stderr.flush()
    sys.stderr.write("\n")
    print(f"OK — wrote {args.output} ({done} rows, {errors} errors)",
          file=sys.stderr)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
