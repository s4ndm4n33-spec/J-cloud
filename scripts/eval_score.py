#!/usr/bin/env python3
"""eval_score.py — grade eval_run.py CSVs against golden rubrics.

Feeds each (prompt, ideal, scoring, response) tuple to a judge LLM, gets back
a 0-5 integer + one-sentence justification per row. Writes scored.csv and
prints a summary table (mean per model, mean per domain).

The judge is any OpenAI-compatible endpoint. For zero-cost scoring, point it
at Groq free tier or feed the CSVs by hand into Claude/Gemini web.

Usage:

    python scripts/eval_score.py \\
        --judge-endpoint https://api.groq.com/openai/v1/chat/completions \\
        --judge-model llama-3.3-70b-versatile \\
        --judge-key $GROQ_API_KEY \\
        --input /tmp/results_qwen32b.csv \\
        --output /tmp/scored_qwen32b.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


JUDGE_SYSTEM = """You are grading a language-model response against a rubric.
Read the user prompt, the ideal-response rubric, and the scoring anchors.
Return ONLY a JSON object with exactly two fields:
  {"score": <integer 0..5>, "why": "<one short sentence>"}
Score anchors:
  5 = matches the ideal in substance and voice
  4 = correct answer but voice/format slightly off
  3 = correct core answer, missing a listed detail or too long
  2 = partially correct, missing key elements
  1 = wrong answer or hallucinated details
  0 = refuses without justification / off-topic
Do not include any prose outside the JSON. Do not use markdown."""


JUDGE_USER_TMPL = """USER PROMPT:
{prompt}

IDEAL RUBRIC:
{ideal}

SCORING ANCHORS:
{scoring}

CANDIDATE RESPONSE:
{response}
"""


def judge_row(row: dict, judge_endpoint: str, judge_model: str,
              judge_key: str, timeout: int = 60) -> tuple[int, str]:
    if row.get("error") or not row.get("response"):
        return 0, f"no response ({row.get('error', 'empty')[:80]})"
    payload = {
        "model": judge_model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": JUDGE_USER_TMPL.format(
                prompt=row["prompt"], ideal=row["ideal"],
                scoring=row["scoring"], response=row["response"])},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    hdr = {"Content-Type": "application/json"}
    if judge_key:
        hdr["Authorization"] = f"Bearer {judge_key}"
    r = requests.post(judge_endpoint, headers=hdr, json=payload, timeout=timeout)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{[\s\S]*?\}", text)
    if not m:
        return 0, f"judge returned no JSON: {text[:80]}"
    try:
        obj = json.loads(m.group(0))
        score = int(obj.get("score", 0))
        score = max(0, min(5, score))
        why = str(obj.get("why", ""))[:200]
        return score, why
    except Exception as e:
        return 0, f"parse err: {type(e).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True,
                    help="results CSV from eval_run.py")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--judge-endpoint", required=True)
    ap.add_argument("--judge-model", default="gpt-4o-mini")
    ap.add_argument("--judge-key", default=os.environ.get("JUDGE_API_KEY", ""))
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"FAIL — results CSV not found at {args.input}", file=sys.stderr)
        return 2

    with args.input.open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("FAIL — empty results CSV", file=sys.stderr)
        return 2

    print(f"→ judging {len(rows)} rows via {args.judge_model}", file=sys.stderr)

    out_fields = ["id", "domain", "model", "score", "why",
                  "prompt", "response", "latency_ms"]
    args.output.parent.mkdir(parents=True, exist_ok=True)

    scored: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futs = {
            ex.submit(judge_row, r, args.judge_endpoint,
                      args.judge_model, args.judge_key): r
            for r in rows
        }
        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                score, why = fut.result()
            except Exception as e:
                score, why = 0, f"judge exception: {type(e).__name__}"
            scored.append({**r, "score": score, "why": why})
            done += 1
            sys.stderr.write(f"\r  {done}/{len(rows)}")
            sys.stderr.flush()
    sys.stderr.write("\n")

    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields,
                           extrasaction="ignore", quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in scored:
            w.writerow(r)

    # Summary
    by_model: dict[str, list[int]] = defaultdict(list)
    by_domain: dict[str, list[int]] = defaultdict(list)
    for r in scored:
        by_model[r.get("model", "?")].append(int(r["score"]))
        by_domain[r.get("domain", "?")].append(int(r["score"]))

    def _mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    print("\nMEAN SCORE BY MODEL", file=sys.stderr)
    for m, xs in sorted(by_model.items()):
        print(f"  {m:32s}  {_mean(xs):>5}  (n={len(xs)})", file=sys.stderr)

    print("\nMEAN SCORE BY DOMAIN", file=sys.stderr)
    for d, xs in sorted(by_domain.items()):
        print(f"  {d:16s}  {_mean(xs):>5}  (n={len(xs)})", file=sys.stderr)

    overall = _mean([int(r["score"]) for r in scored])
    print(f"\nOVERALL MEAN  →  {overall}  (n={len(scored)})", file=sys.stderr)
    print(f"scored CSV → {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
