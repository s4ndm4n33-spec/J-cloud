# The Workflow — get the band together

> ME → E1 → free-tier LLM → E1 → ME → J
>
> Six hops. Each one earns its place. This doc is what makes the loop reliable
> instead of a vibe.

---

## Who does what

```
+---------+     goals, priorities, "ship it"
|   ME    |◄─────────────────────────────────┐
|  (you)  |                                  │
+---------+                                  │
     │                                       │
     │ 1. "Build X because Y"                │ 6. Review + deploy
     ▼                                       │
+-----------+     spec (SPEC_TEMPLATE.md)    │
|    E1     |─────────────────────────►      │
| (me, J's  |                                │
|architect) |◄────── code (files) ───────    │
+-----------+                    │           │
     │                           │           │
     │ 2. CIG-standard spec      │ 4. Files  │
     ▼                           │           │
+-----------+                    │           │
| free tier |◄─── paste spec ────┘           │
|   LLM     |                                │
| (Copilot, |──── return files ──────────►   │
|  GPT web, |                                │
|  Claude,  |                                │
|  Gemini)  |                                │
+-----------+                                │
                                             │
     ┌───────────────────────────────────────┘
     │ 5. YOU paste returned files back into chat with E1
     │    (Emergent does NOT auto-sync GitHub → Preview.
     │     GitHub is for shipping clean state OUT, not
     │     pulling drafts IN. See §"Sync reality" below.)
     ▼
+---------+
|    J    |    (deployed at https://blue-j-gauntlet.com after
+---------+     you hit Deploy)
```

## Sync reality — how code actually enters the preview pod

Confirmed with Emergent support. There are exactly three supported paths for
code to enter the preview environment:

1. **The E1 agent writes it** (default — this is me).
2. **File attachments in chat**: paperclip icon → upload the files returned
   by the free-tier LLM → I ingest and apply them.
3. **"Pull from GitHub"** UI button: if the free-tier LLM's output is
   already on a branch you control, push it there from your laptop first,
   then click the GitHub button in the Emergent chat to pull it into `/app`.

**"Save to GitHub" is push-only**. Editing files on github.com does NOT
propagate back to the preview pod automatically. Every drop into `/app` has
to go through one of the three paths above.

**Practical implication for our workflow**: after step 4 (LLM returns files),
you paste them straight back into chat with me — no GitHub round-trip
needed. GitHub is for committing the finished, gauntlet-passed state OUT so
you have version history, not for shuttling drafts back in.

## Roles, honest

| Hop | Actor | Job | Not their job |
|---|---|---|---|
| 1 | You | Set direction. Decide priority. Own the roadmap. | Writing code. |
| 2 | E1 (me) | Author the spec. Cite files, constraints, testids, acceptance test. | Typing every line myself. |
| 3 | Free-tier LLM | Implement to spec. Return full files. | Deciding architecture, adding scope. |
| 4 | Free-tier LLM | Same. | Explaining what it did — commentary wastes context. |
| 5 | E1 (me) | Run the 20-point review. Bounce or pass. Apply to `/app`. Trigger tests. | Deploying — that's your gate. |
| 6 | You | Smoke check. Save to GitHub (for version history). Hit Deploy. Ship to J. | Debugging CIG rejections — that's my job. |

## When to skip the loop and just have me do it

Not every task belongs in this workflow. Route to me directly when:

- **Anything on J's substrate — non-negotiable**: CIG (`code_integrity.py`),
  persona (`persona.py`), agent loop (`routes/ai.py`), chronicle
  (`chronicle.py`), J:MIND (`core/knowledge.py`, `routes/knowledge.py`),
  ambient awareness (`core/ambient.py`), voice (`routes/voice.py`), tools
  (`core/tools.py`), destructive interlock (`core/destructive.py`),
  Five Masters gauntlet (`core/fivemasters.py`). **No free-tier LLM touches
  these. Ever. E1 writes; the user reviews; then it ships.** This is the
  rule that keeps J deterministic across model swaps.
- **Cross-cutting integration**: any 3rd party (Tavily, Stripe, Whisper, TTS,
  OAuth, GitHub API) — I own these end-to-end because I have the integration
  playbook expert and the Emergent LLM key wiring in my toolbelt.
- **Cross-file debugging**: any bug where the fix touches ≥3 files or the
  root cause is upstream of the symptom.
- **Anything under 30 lines and time-sensitive**: the round-trip through a
  free-tier tool costs more than the code.
- **After a bounce**: if the free-tier LLM bounces twice on the same task,
  hand it to me. Two bounces means the spec was ambiguous OR the task was
  actually cross-cutting; either way, human context matters.

## When the loop shines

- **Marketing site / landing pages**: exemplary free-tier task. Clear scope,
  visual, self-contained, testable in a browser.
- **Individual React components** with a spec: MIND panel-style widgets,
  form components, small data tables.
- **CRUD endpoint families** where the schema is handed over: `POST /api/X`,
  `GET /api/X`, `DELETE /api/X/{id}` — churn work.
- **Unit tests for pure modules**: write the test spec, get 20 tests back.
- **Copy edits, styling passes, `data-testid` sweeps**: mechanical work that
  benefits from a fresh set of eyes and doesn't need context.

## Cost model — why this is a good deal

| Task type | Solo E1 (me) | With free-tier loop |
|---|---|---|
| Marketing landing page | ~1 hour, drains my context | 20 min spec + 15 min review = 35 min, my context stays fresh for the hard stuff |
| New CRUD endpoint family | ~45 min | 15 min spec + 15 min review = 30 min |
| Small React component | ~30 min | 10 min spec + 10 min review = 20 min |
| Cross-file integration | 1-2 hours | **same 1-2 hours** — do NOT route this out |
| CIG-adjacent bug | 30-60 min | **same 30-60 min** — do NOT route this out |

The win isn't per-task speed. It's that my context stays clean for the tasks
where I actually matter, and you can run 3-5 free-tier tasks in parallel
whereas I'm serial.

## A worked example — the marketing site

Suppose the next task is: *"Build a marketing landing page at `/` with hero,
feature grid showing the JARVIS-tier checklist, live MIND panel demo, and
waitlist signup."*

**1. YOU say:** "Build the marketing site. Route it at `/`. Hero + feature
grid + JARVIS checklist showcase + waitlist. Match the current cyan/steel
palette. Waitlist emails go to Mongo for now."

**2. I produce a spec** (using SPEC_TEMPLATE.md) — probably 3 tasks split
because a landing page hits ~600 LOC:

- `LAND-1`: Route + shell layout + Hero (S, ~150 LOC)
- `LAND-2`: Feature grid + JARVIS checklist section (S, ~200 LOC)
- `LAND-3`: Waitlist form + `POST /api/waitlist` + test (M, ~250 LOC)

I hand each spec to you as a paste-ready markdown block.

**3. YOU paste `LAND-1` into Copilot / Claude web / whatever has quota.**
Wait ~2 minutes.

**4. YOU paste the returned files into a chat with me:** "here's LAND-1
back."

**5. I run the 20-point review.** Either:
- **BOUNCE §11, §13** — testids missing on the waitlist input, hex colour
  `#0aa8bf` instead of `var(--cyan)`. You paste my bounce message back into
  Copilot. Loop.
- **PASS** — I write the files to `/app`, restart services, run the
  acceptance test, screenshot, and hand you a ship-ready diff.

**6. YOU deploy.** J now has a marketing site.

Total elapsed: probably 35-45 minutes for the whole landing page instead of
2+ hours if I typed it. And I still have full context for the next hard
integration you throw at me.

## The two documents that make this real

Both live in this folder:

1. **`SPEC_TEMPLATE.md`** — the exact format I ship every spec in. Copy-paste-fill.
2. **`REVIEW_CHECKLIST.md`** — the 20-point gauntlet I run before anything
   hits `/app`. You can run it too if you want a sanity check.

## The rule that keeps the standard from slipping

**Every task, no exceptions, must have an acceptance test file.** If the
free-tier LLM forgets it — bounce. If you tell me "just ship it, we don't
need the test for this one" — I will politely push back. The test is what
makes the framework a framework instead of a habit. It's what lets you sleep
knowing the next feature didn't quietly break the previous one.

That's the whole show. Let's take it on the road.
