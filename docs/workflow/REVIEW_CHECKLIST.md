# Review Checklist — the gauntlet I run on returned code before you ship

> Twenty points. I run them in order on anything a free-tier LLM ships back.
> First fail stops the review; the code goes back with the specific violation
> quoted. No "close enough". The point of the framework is that the standard
> doesn't slip when the author does.

---

## Tier 1 — Structural (fails 1-4 = automatic bounce)

**1. Truncation markers**
Grep the diff for `... rest`, `... existing`, `// ...`, `# ...`, `<!-- ... -->`,
`REST OF FILE`, `unchanged from above`. Any hit = rewrite. This is what CIG
catches automatically; catch it first so we don't waste a CIG cycle.

**2. Complete files, not diffs**
Every file returned must be the full file. If it starts with `@@` or contains
`... (existing code) ...`, reject.

**3. File scope respected**
Diff files vs the CREATE/EDIT/DELETE list in §3 of the spec. Any extra file
touched is a bounce — even "improvements". Especially "improvements."

**4. No dependency drift**
Check `git diff -- requirements.txt package.json`. Any change here without
explicit spec justification is a bounce. Deps must be installed via `pip
install X && pip freeze > requirements.txt` (backend) or `yarn add X`
(frontend), never hand-edited.

---

## Tier 2 — Correctness (5-10)

**5. `/api` prefix on every backend route**
Grep `@router.(get|post|put|delete|patch)("` and confirm the path starts with
`/`. All routers are mounted under `/api` in `server.py` — a route without a
leading `/` or with `/api/api/...` is broken.

**6. Environment variables**
Grep `os.environ.get(` — any default value fallback is a bounce. Use
`os.environ["KEY"]` so missing config fails fast. Same rule for `process.env`
in JS.

**7. Datetime discipline**
Grep `datetime.utcnow()` — bounce. Must be `datetime.now(timezone.utc)`. If
serialised, must be `.isoformat()` before hitting Mongo.

**8. MongoDB ObjectId leakage**
Grep response objects for `_id` — reject if returned raw. Either project it
out (`{"_id": 0}`) or coerce to string.

**9. Bare / silent excepts**
Grep `except:` or `except Exception:\s*pass`. Bounce. Errors must either be
logged with context, converted to an `HTTPException`, or explicitly commented
as intentional (rare).

**10. Mutable default arguments**
Grep `def .*=\s*(\[\]|\{\}|dict\(\)|list\(\))` — Python function signatures.
Bounce.

---

## Tier 3 — Frontend hygiene (11-14)

**11. `data-testid` present on every interactive element**
Every `<button>`, `<input>`, `<textarea>`, `<select>`, `<a>` (that navigates
inside the app), and every element carrying user-critical info (counters,
error messages, empty states) must have a unique kebab-case `data-testid`.
No exceptions. Use grep: `grep -E "<(button|input|textarea|select)\s" file
| grep -v data-testid` — any hit is a bounce.

**12. Absolute URLs use `REACT_APP_BACKEND_URL`**
Grep the diff for `localhost:8001`, `http://127.0.0.1`, or hard-coded prod
hostnames. Bounce.

**13. Design tokens, not raw values**
Grep the diff for hex colours (`#[0-9a-fA-F]{3,8}`) that aren't already in
`index.css` — bounce. Same for `text-[16px]`, `mt-[7px]` — no arbitrary
Tailwind values without a documented reason.

**14. No emoji in UI or copy**
Grep the diff for emoji using: `python3 -c "import sys,re; [print(l) for l
in open(sys.argv[1]) if re.search(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF]', l)]"`.
Icons live in `@phosphor-icons/react`. Bounce on any hit.

---

## Tier 4 — Testability (15-17)

**15. Acceptance test present and runs**
Confirm the file at the path named in the spec's §9 exists. Run it locally.
If it needs credentials it doesn't have (Tavily, Emergent LLM key, etc.),
confirm the test skips cleanly with `pytest.skip()` rather than failing.

**16. Test uses `REACT_APP_BACKEND_URL`, not localhost**
Same rule as §12 — but for backend tests. External URL only.

**17. No stray print/console.log/TODO in shipped code**
Grep `\bprint\(`, `console\.(log|debug)`, `# TODO`, `// TODO`, `FIXME`. Any
hit in the diff outside a test file is a bounce.

---

## Tier 5 — Craft (18-20; warn but don't block)

**18. Function length**
Any function >50 lines gets a warning + suggested split. Not blocking on its
own but combined with §19 is a bounce.

**19. Cyclomatic sanity**
Any function with >3 nested blocks OR >6 branches gets flagged. Refactor request.

**20. Persona respected in any user-facing string**
If the change added text J speaks or displays: read it out loud. If it sounds
like sycophancy, corporate PR, or a Slack channel emoji-post, bounce with a
rewrite of one example line.

---

## The bounce message format

When I bounce, I send back exactly this — no more, no less:

```
BOUNCE — <TASK-ID>

Failed checks: <list of numbers from above, e.g. §7, §11, §15>

Cited violations:
  - <file>:<line> — <exact offending code>
  - <file>:<line> — <exact offending code>

Return the FULL FILES again with these fixed. Do not attempt to explain the
bounce — just fix and resubmit.
```

Terse is intentional. The LLM should not spend cycles apologising; it should
spend them shipping the fix.

## The pass message

When a pass:

```
PASS — <TASK-ID>

Applied to /app. Backend restarted / frontend hot-reloaded.
Acceptance test: PASS (<n>/<n>).
Ready for your review before deploy.
```

Then you (the human) do a final smoke check and hit deploy.
