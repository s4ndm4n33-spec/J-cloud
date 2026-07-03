# Task Spec Template — the format I ship every hand-off in

> Every task you route to a free-tier code assistant (Copilot / Codex / GPT web
> / Claude web / Gemini) should be a **spec, not a prompt**. Vague prompts get
> vague code. This template is the format I generate before any hand-off; you
> paste it verbatim into whichever tool has quota left.
>
> Fill it out top-to-bottom. Empty sections stay in — an omitted "out of scope"
> line is how you get a rewrite you didn't ask for.

---

## [TASK-ID]  <one-line title, imperative mood>

**Owner**: <you>
**Author of this spec**: J (via E1)
**Target LLM**: <Copilot | GPT web | Claude web | Gemini | Codex>
**Estimated size**: <XS ≤50 LOC | S ≤200 | M ≤500 | L split-me-up>

---

### 1. Goal (one sentence, user-facing)
> "As a <user>, I can <verb-phrase> so that <outcome>."

### 2. Why now
2-4 sentences of context. What triggered this. What breaks if we don't ship it. Any user quote goes here verbatim.

### 3. Files to touch (exhaustive; anything else is out-of-scope)
```
CREATE  path/to/new_file.ext        — <one-line reason>
EDIT    path/to/existing.ext        — <one-line reason>
DELETE  path/to/dead_file.ext       — <one-line reason>
```

### 4. Data / API contract (backend tasks)
```
METHOD  /api/<route>
  Request  { field: type, ... }
  Response { field: type, ... }
  Errors   400 { detail } | 404 | 502
  Auth     Bearer session_token in Authorization header
```

MongoDB collections touched + document shape:
```
db.<collection>: { id: str, ...fields..., ts: iso-8601 utc }
```

### 5. UI contract (frontend tasks)
- Component tree diagram (ASCII is fine)
- Every interactive element must carry `data-testid` — list them here:
  - `<component-name>-<action>-btn`
  - `<component-name>-<field>-input`
- Copy for buttons / labels / empty states / error toasts — verbatim
- Which shadcn/ui components to reuse (`/app/frontend/src/components/ui/`)

### 6. Design tokens (frontend)
- Colours: use CSS vars from `/app/frontend/src/index.css` — do NOT introduce hex codes
- Font stacks: `font-display` (headers), `font-mono` (chrome/data)
- Spacing: multiples of 4px only
- Icons: `@phosphor-icons/react` only. No emoji.

### 7. CIG constraints (non-negotiable)
The Code Integrity Gateway will reject any of the following. Do not emit them:
- `...rest unchanged...` / `// ... existing code ...` / any placeholder comment
- `except:` (bare) or `except Exception: pass`
- Mutable default args (`def f(x=[]):`)
- `range(len(x))` — enumerate or iterate directly
- `datetime.utcnow()` — use `datetime.now(timezone.utc)`
- Raw MongoDB ObjectId in responses — always serialise as str
- Missing `/api` prefix on backend routes
- Environment variables with hard-coded fallbacks — `os.environ["KEY"]` only, no `.get(default)`
- Frontend making direct calls to `localhost:8001` — always `REACT_APP_BACKEND_URL`

### 8. Persona alignment (agent-facing text)
If this task adds text J speaks or displays:
- Voice: sharp, sardonic, kind. No sycophancy ("Great question!"). No emoji.
- Format: markdown; short lines; ASCII status glyphs (OK / FAIL / WARN) not emoji.
- Length: default to fewer sentences. J earns adjectives; she doesn't spend them.

### 9. Acceptance test (must ship with the code)
Provide ONE test file at the end of your implementation:

- **Backend**: pytest at `/app/backend/tests/test_<feature>.py` calling the real
  endpoint via requests using `REACT_APP_BACKEND_URL`. Include one happy path +
  one failure path + one auth-negative case.
- **Frontend**: describe (don't write) a Playwright scenario using the
  `data-testid`s from §5 — the E1 testing agent will build the actual script.

### 10. Out of scope (protective)
List everything a well-meaning LLM might "improve" if you don't nail it down:
- Do NOT refactor <adjacent module>
- Do NOT rename existing routes
- Do NOT add new dependencies without justification here
- Do NOT change the Emergent LLM key wiring
- Do NOT touch `.env` files, `requirements.txt`, or `package.json` directly —
  use `pip install X && pip freeze > requirements.txt` / `yarn add X`
- Do NOT add "helpful" logging, retries, or fallbacks not listed in §4

### 11. Definition of Done checklist (LLM ticks these before returning)
- [ ] All files in §3 are present, no others touched
- [ ] All CIG constraints in §7 respected — self-verify
- [ ] All testids in §5 present on the correct elements
- [ ] Acceptance test in §9 is included and runs green locally
- [ ] `yarn build` (frontend) or `python -c 'import backend.server'` (backend) succeeds
- [ ] No stray `console.log`, `print()`, or `TODO` left in shipped code
- [ ] Copy in §5 is used verbatim — no LLM-invented labels

---

### 12. Return format
Return your work as a set of complete files, one per code block, each preceded
by `# FILE: /absolute/path` on its own line. Do NOT return diffs. Do NOT
return partial files. Do NOT summarise the changes — the diff tool will do
that. Just the files.

*Ship code, not commentary.*
