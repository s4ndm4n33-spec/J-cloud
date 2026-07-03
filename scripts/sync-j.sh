#!/usr/bin/env bash
# sync-j.sh — fan out AGENTS.md to every IDE-specific rule file.
#
# Canonical source: /AGENTS.md
# Destinations: Cursor, GitHub Copilot, Claude Code, Windsurf, Continue, Zed
#
# Run whenever you edit AGENTS.md so J stays consistent across every IDE any
# collaborator opens the repo in.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/AGENTS.md"

if [[ ! -f "$SRC" ]]; then
  echo "FAIL — /AGENTS.md not found; nothing to sync" >&2
  exit 1
fi

# Cursor — .cursor/rules/j.mdc  (Cursor uses .mdc with frontmatter metadata)
mkdir -p "$ROOT/.cursor/rules"
{
  echo "---"
  echo "description: J, the Sovereign Master persona. Applies to every file."
  echo "alwaysApply: true"
  echo "---"
  echo
  cat "$SRC"
} > "$ROOT/.cursor/rules/j.mdc"

# GitHub Copilot (VS Code) — .github/copilot-instructions.md
mkdir -p "$ROOT/.github"
cp "$SRC" "$ROOT/.github/copilot-instructions.md"

# Claude Code / Anthropic — CLAUDE.md
cp "$SRC" "$ROOT/CLAUDE.md"

# Windsurf — .windsurfrules  (plain markdown; no extension convention)
cp "$SRC" "$ROOT/.windsurfrules"

# Continue — .continue/rules.md
mkdir -p "$ROOT/.continue"
cp "$SRC" "$ROOT/.continue/rules.md"

# Zed — .zed/agent.md
mkdir -p "$ROOT/.zed"
cp "$SRC" "$ROOT/.zed/agent.md"

# Aider — the AGENTS.md convention (canonical) is already at repo root.
# Aider reads it natively; no action needed.

# Codex CLI — reads AGENTS.md natively; no action needed.

echo "OK — J synced to:"
echo "  .cursor/rules/j.mdc"
echo "  .github/copilot-instructions.md"
echo "  CLAUDE.md"
echo "  .windsurfrules"
echo "  .continue/rules.md"
echo "  .zed/agent.md"
echo
echo "AGENTS.md (repo root) is the canonical source — edit there, re-run this."
