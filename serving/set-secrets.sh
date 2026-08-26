#!/usr/bin/env bash
# Push every value from secrets.env into Cerebrium as a named secret.
# Skips blanks (e.g. HUGGINGFACE_HUB_TOKEN if you haven't set one).
#
# Usage:
#     cd /app/serving/
#     cerebrium login              # once
#     ./set-secrets.sh             # every time secrets.env changes
#
# Safe to re-run — Cerebrium's `secrets set` is upsert semantics.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${HERE}/secrets.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found." >&2
  exit 1
fi

if ! command -v cerebrium >/dev/null 2>&1; then
  echo "ERROR: cerebrium CLI not on PATH. Install with: pip install cerebrium" >&2
  exit 1
fi

pushed=0
skipped=0

# Read the file line-by-line — resistant to quoting weirdness in values.
while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip comments + blanks
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  # Split at first `=` only
  key="${line%%=*}"
  val="${line#*=}"
  key="$(echo "$key" | xargs)"                     # trim
  # Strip optional surrounding quotes
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"

  if [[ -z "$val" ]]; then
    echo "  skip  $key   (empty)"
    skipped=$((skipped + 1))
    continue
  fi

  echo "  push  $key"
  cerebrium secrets set "$key" "$val" >/dev/null
  pushed=$((pushed + 1))
done < "$ENV_FILE"

echo ""
echo "done — pushed=$pushed  skipped=$skipped"
echo "next: cerebrium deploy"
