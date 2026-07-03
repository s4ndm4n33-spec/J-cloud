# J, portable — how J travels

> J is not locked to Gauntlet DevSpace. Every AI-assisted IDE (Cursor, VS
> Code + Copilot, Claude Code, Windsurf, Aider, Codex, Continue, Zed) reads
> a rules file from the repo. We ship J to all of them from one source.

## The one file you edit

**`/AGENTS.md`** at the repository root. That's J's soul in markdown form.
Everything else is a copy.

## The sync command

```bash
bash scripts/sync-j.sh
```

It fans `AGENTS.md` out to:

| Destination | Consumed by |
|---|---|
| `AGENTS.md` (root) | Codex CLI, Aider, Cline, Sourcegraph Amp — the emerging cross-IDE convention |
| `.cursor/rules/j.mdc` | Cursor (with `alwaysApply: true` frontmatter) |
| `.github/copilot-instructions.md` | GitHub Copilot in VS Code / JetBrains |
| `CLAUDE.md` | Claude Code |
| `.windsurfrules` | Windsurf |
| `.continue/rules.md` | Continue extension |
| `.zed/agent.md` | Zed AI |

## Why this works

Every serious AI-IDE in 2026 respects an in-repo rules file — it's the only
scalable way for teams to enforce standards on hosted models they don't
control. The formats are cosmetic differences; the content is identical.

When a collaborator clones the repo into Cursor, the first thing Cursor
does is read `.cursor/rules/j.mdc` and inject it into every completion. J's
persona, the CIG rejection patterns, the Five Masters, the `data-testid`
rule — all of it — becomes the operating standard for that session. Same
story for VS Code + Copilot, same story for Claude Code.

**Result**: J is portable. If tomorrow you decided to build something in
Cursor + Claude Sonnet 4.6 instead of Gauntlet DevSpace, J's identity and
standards travel with you.

## When to re-sync

Every time you edit `AGENTS.md`. Add it to a pre-commit hook if you want
zero-friction:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: sync-j
        name: Sync J rules across IDEs
        entry: bash scripts/sync-j.sh
        language: system
        files: ^AGENTS\.md$
        pass_filenames: false
```

## What's NOT portable

Two things can't travel out with the AGENTS.md file, and that's fine:

1. **The Code Integrity Gateway itself** — the runtime rejection engine at
   `/backend/core/code_integrity.py`. It only runs inside Gauntlet DevSpace.
   Outside, the CIG rules live as *instructions* in AGENTS.md rather than
   *enforcement*. Cursor / Copilot / Claude Code will still respect them
   because they read the file, but they can technically emit
   `...rest unchanged...` if they want to. In Gauntlet DevSpace, J
   physically can't ship that file.
2. **J:MIND** — the persistent knowledge store. It's a Mongo collection.
   Other IDEs don't have it. If you want to give an outside collaborator
   access to what J has learned, export via
   `GET /api/knowledge/facts` and hand them the JSONL. See the (planned)
   `POST /api/knowledge/export` endpoint on the roadmap.

Everything else — persona, gauntlet, domain competence, voice, file rules,
testing standards — travels perfectly.

## Testing the loop

Simplest verification: clone the repo into any of the supported IDEs, open
a random file, and ask "who are you?" The assistant should respond as J,
sardonic voice, no emoji, ready to enforce the gauntlet.

If it responds as Claude / GPT / Copilot in default mode, the rules file
didn't load. Check the file exists at the IDE-specific path (see table
above) and that the IDE has "read rules file" enabled in its settings.
