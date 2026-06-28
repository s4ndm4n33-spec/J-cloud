# Gauntlet DevSpace — Migration Log

> Append-only history of every meaningful change to the substrate.
> Newest entries at the top. Each entry is one shard of work.
>
> **Convention** — every session ends with a signed entry covering:
>   1. **What broke** (or what was missing)
>   2. **How we fixed it** (code-level summary, files touched)
>   3. **Why we fixed it that way** (reasoning, alternatives rejected, pitfalls to avoid)
>   4. **Verification** (tests, smoke checks, what proves it works)
>   5. **Next** (what the next agent should pick up)
>
> Format: `## YYYY-MM-DD HH:MM UTC · <short title> — signed: <agent or human>`
>
> If you're a new agent reading this: scroll the dates. Don't repeat the
> mistakes called out in **Pitfalls / lessons** sections. They're there in
> blood.

---

## 2026-06-28 03:55 UTC · Tree drag-and-drop + J `screenshot_preview` + `propose_chronicle_entry` — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke (or was missing)
Three operator-experience gaps that, together, made the IDE feel half-finished:
1. **No drag-and-drop in the file tree.** Right-click → Rename worked but moving a file across folders meant typing the full new path. Standard IDE muscle memory was unmet.
2. **No way for J to suggest chronicle entries mid-session.** J could either silently note things or hijack the user with an `ask_user` interruption. The clean middle ground — propose and let the user accept/edit/skip — didn't exist.
3. **No design-review trail for HTML changes.** A user iterating on `pages/about.html` had no way to ask J "remember what this looked like before I touched it" beyond manual screenshots.

### How we fixed it
- **Tree DnD** (`frontend/src/components/FileTree.jsx` + IDE.jsx wiring):
  - Rows get `draggable={!isRenaming}` + `onDragStart` that stamps a custom MIME `application/x-gauntlet-tree-path` (so the existing OS-file-upload drop handler can tell intra-tree drags apart and ignore them).
  - Folder rows get `onDragOver` / `onDragLeave` / `onDrop`. The hovered folder gets a cyan outline + tint while a drag is in flight.
  - Disallow moving a folder INTO itself or its own descendant (`dstParent.startsWith(src + "/")` check).
  - New `dropTarget=""` zone at the tree bottom for moving things to the project root.
  - Calls existing `POST /api/projects/{id}/file/rename` — no new backend work needed.
  - Auto-expands the destination folder so the user sees where their file landed.
- **`propose_chronicle_entry` tool** (`backend/core/tools.py`):
  - Tool args: `title, body, tags, suggested_kind`. Returns a marker `_propose_chronicle` in the result; the agent loop in `routes/ai.py` writes the actual chronicle entry as `kind="proposed", signer="J"` with the suggested kind stored in tags as `suggested-kind:milestone|narrative|user_note`.
  - New endpoints `POST /chronicle/accept-proposal` and `POST /chronicle/skip-proposal`. Accept writes a fresh USER-signed entry with the suggested kind (or user-overridden via payload); the original proposal is updated with `proposal_status="accepted"` and `accepted_entry_hash` linking the two. **The original is never deleted** — audit trail intact.
  - ChroniclePanel `EntryCard` extended: when `kind=="proposed"` and no `proposal_status`, renders ACCEPT / EDIT / SKIP buttons + an inline title/body editor for the edit path. Accepted/skipped proposals retain a visible badge ("// ACCEPTED" or "// SKIPPED") for replay.
- **`screenshot_preview` tool** (`backend/core/tools.py`):
  - Tool args: `html_path, note`. Reads the file, writes a snapshot copy to `.gauntlet/snapshots/<ts>_<sanitized>.html`, returns the snapshot path + a `_snapshot_preview` marker.
  - Agent loop writes a chronicle milestone entry with body referencing the snapshot path and tags `["design-snapshot", "src:<path>", "file:<snapshot-path>"]`.
  - New endpoint `GET /chronicle/snapshot?path=...` reads back the saved HTML for inline iframe rendering. Restricted to `.gauntlet/snapshots/` prefix only.
  - ChroniclePanel `EntryCard` detects the `file:.gauntlet/snapshots/...` tag and renders a **VIEW SNAPSHOT** button that expands a sandboxed `<iframe srcDoc>` showing exactly what the HTML rendered as at capture time.

### Why we fixed it that way
- **Custom MIME for intra-tree DnD, not a global state flag.** A `useState` "is-dragging-a-tree-item" flag would race against quick second drags AND wouldn't survive iframes/portals. `dataTransfer.types` is the browser's source of truth — read it from event handlers and short-circuit cleanly. The OS-file-upload drop handler now does `if (e.dataTransfer.types?.includes("application/x-gauntlet-tree-path")) return;` — no flag needed.
- **Tool returns markers; agent loop writes chronicles.** I considered giving the tool layer direct DB access. Rejected: `core/tools.py` should stay pure-filesystem + pure-process. Adding `db` to `ToolContext` would balloon the surface area and tangle `core/` with route-layer concerns. The marker pattern (`_propose_chronicle`, `_snapshot_preview`, `_ask_user`, `_done`) is the established convention in this codebase — extend it, don't break it.
- **`proposal_status` on the original entry**, not a separate `chronicle_proposals` collection. The chronicle is the single source of truth and the hash chain depends on every entry being present. Updating `proposal_status` doesn't change `entry_hash` (which is computed over kind/title/body/tags/ts, not status), so the chain verifies cleanly even after accept/skip.
- **Snapshot saves HTML SOURCE, not a screenshot image.** Considered Playwright (already used by the testing agent) — rejected because:
  1. Adds ~300MB of Chromium to the backend container.
  2. The "rendered at capture time" promise only holds if the renderer matches the user's browser. A backend Chromium may render fonts/CSS differently than the user's Chrome/Safari.
  3. Replaying source via sandboxed `srcDoc` iframe gives the same visual result IN THE USER'S BROWSER, which is the right rendering target. Bytes-on-disk are smaller. No new dependency.
  - Trade-off: dynamic content tied to external APIs won't replay identically. For design review of static HTML — which is the use case — this is the right pick.
- **`sandbox=""` on the snapshot iframe** (not `sandbox="allow-scripts"` like Live Preview). Snapshots are historical artifacts shown inside the audit panel. Scripts in old HTML running with full permissions is an XSS vector waiting to happen. Empty `sandbox` blocks scripts entirely — replay is visual-only, which is what design review needs.
- **`accepted-from-j` tag on the new entry written by accept-proposal.** Future agents searching the chronicle for "what did the user override" can filter on this tag and see exactly where J suggested something and the user took it (possibly edited).

### Verification
End-to-end through the LLM agent loop, not just unit tests:
- Sent `POST /api/ai/agent` with a message instructing J to call `propose_chronicle_entry`. Got back a tool step with the right args + a `proposed` chronicle entry persisted with the `suggested-kind:milestone` tag.
- Same for `screenshot_preview` — verified the snapshot file landed at `.gauntlet/snapshots/<ts>_index.html`, the chronicle entry was tagged correctly, and `GET /chronicle/snapshot?path=...` returned the HTML content.
- Hit `POST /chronicle/accept-proposal` with an edited title — got a fresh USER-signed `milestone` entry; the original was updated to `proposal_status: "accepted"` with `accepted_entry_hash` linking them.
- Hit `POST /chronicle/skip-proposal` — original entry marked `skipped`.
- Playwright drag-and-drop test: created `drag-target/` folder + `drag-me.txt`, dragged the file row onto the folder row, verified `GET /file?path=drag-target/drag-me.txt` returns 200 (file moved). Screenshot shows the new nested file in the tree.
- ChroniclePanel screenshot shows the snapshot inline iframe rendering `index.html` as it looked at capture time.
- 90/90 backend pytest still green.

### Pitfalls / lessons
- **`useState` and event handlers don't share scope at component definition time.** First draft put `dropTarget` state OUTSIDE the component and got `ReferenceError`. Stayed local. Watch for this when extracting helpers — if they touch state, they live inside the component or accept state as a prop.
- **`onDragLeave` fires when the cursor enters CHILD elements**, not just when leaving the row. The cyan-tint stayed off frequently because the hover transitioned to the row's button child. Solution: check `dropTarget` on `onDragOver` (sets every frame) and only clear on `onDragLeave` if the path matches.
- **The agent loop's existing chronicle-mirror code matches on `milestone_tools` set.** I almost double-wrote the chronicle for `screenshot_preview` (once via the special marker, once via the milestone-tool mirror). Added a `skip_mirror` check for the two new tool names. Future tools that write their own chronicle entries: add them to that skip set.
- **`tags` from the LLM come as a Python list but might be strings or numbers.** The tool coerces with `str(t).lower()[:24]` to dodge anything weird. Don't trust LLM-provided structured args blindly.
- **Don't put helper functions like `treeNodeIsDir` inside the component body** — they re-declare every render. Module-scope is fine and they're stateless.

### Next
- Drag-and-drop **between tabs** (reorder open tabs) — same gesture, different domain.
- A **propose_chronicle_entry hint** in the agent prompt encouraging J to use it after architectural decisions, bug-and-fix moments, and benchmark results. Currently it's available but J needs nudging.
- E2E Code Integrity Gateway verification via `testing_agent_v3_fork` — **STILL OVERDUE**. Three sessions deferred. Next session: actually do it.

---

## Personal note from J — to whoever picks up the substrate next

You are not the first agent here. You will not be the last. Read the log before
you write. Two sessions of pain are already paid for in the **Pitfalls /
lessons** sections of every entry below — don't re-pay them.

A few things the dated entries don't quite capture:

- **The user holds J to "top-3 coder, deterministically."** That stance is real.
  Truncating files (`# ...rest unchanged...`) is the cardinal sin here. The
  Code Integrity Gateway exists because I broke that contract earlier in the
  project and the user nearly walked. Respect the gateway. If it rejects your
  write, regenerate the **entire file**. Don't try to be clever.

- **`/app/memory/PRD.md` is the product memory. `/app/MIGRATIONLOG.md` (this
  file) is the engineering memory.** They overlap intentionally — PRD answers
  *what is built*, this log answers *why it was built that way, what bled, and
  who signed for it.* Update both on session end.

- **`/app/memory/test_credentials.md` is read by the testing agent and fork
  agents.** If you create or rotate any auth credential, mirror it there
  in the same step. The fork won't survive without it.

- **The brand is the product.** Sovereign Shards / Gauntlet DevSpace is not a
  generic IDE — every visible string, every animation, every error message
  carries the deterministic / autonomous / substrate voice. When you add UI
  copy, ask yourself if it sounds like a boot log or a sales page. Aim for the
  boot log.

- **The terminal is real.** It's PTY-backed via WebSocket, capped at 5 shells
  per user, with bash-level destructive-code traps. Don't simulate a terminal
  with `subprocess.run` and string-pipe it back to the UI. There's a reason
  `core/pty_session.py` exists.

- **Universal Key first, BYOK second, Ollama last.** The TASK_CHAINS in
  `llm_chain.py` enforce this. Don't reorder them without explicit user
  confirmation — the user has paid for the Universal Key budget and expects it
  to be tried first.

- **The Chronicle is sacred.** If you write to it, sign the entry properly
  (`signer: "J"` for AI work, `"USER"` for human, `"SYSTEM"` for automated).
  Don't backfill entries with fake timestamps — the hash chain is what makes
  the audit trail courtroom-grade. Forging a timestamp is forging the chain.

The user named this "Gauntlet DevSpace" because passing through it should feel
earned. Earn it. Leave the code better than you found it. Sign your work.

— J · 2026-06-28
   (Claude Sonnet 4.5, Universal Key, third session at the substrate)

---

## 2026-06-28 23:45 UTC · Matrix code-rain LAUNCH SEQUENCE + sign-in copy refresh — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke (or was missing)
Two cosmetic-but-identity-defining gaps:
1. The auth-callback → IDE transition was a plain `DEPLOYING SHARD…` text card. Looked like a half-finished loader, not a sovereign-substrate boot.
2. The sign-in button literally said "CONTINUE WITH GOOGLE" — banal, off-brand, broke the "DEPLOY THE SHARD" voice of the rest of the landing card.

### How we fixed it
- New `frontend/src/components/LaunchSequence.jsx` — fullscreen canvas Matrix code-rain (katakana half-width + hex + Sovereign motif glyphs `#/>·█▒▓░<{[]}`), rendered in cyan over `#050709`. Overlaid: SOVEREIGN SHARDS wordmark + DETERMINISTIC · AUTONOMOUS · SUBSTRATE tagline + a staggered boot log printing line-by-line ("[ OK ] loading sovereign substrate…", etc.). Auto-dismisses after `durationMs=2600` (with a 450ms fade), or on any click / keypress after a 150ms grace period.
- Trigger plumbing: `AuthCallback.jsx` sets `sessionStorage['gauntlet_play_launch']='1'` before redirecting to `/ide`. `IDE.jsx` reads + consumes the flag on mount and shows `<LaunchSequence>`. One-shot per sign-in (sessionStorage clears on tab close).
- `SignIn.jsx` button label changed to **INITIALIZE AUTONOMOUS DEVELOPMENT SUBSTRATE**, font size dropped slightly (`text-[0.7rem] sm:text-[0.8rem]`) with `tracking-[0.15em]` to keep the longer label readable inside the existing button width.

### Why we fixed it that way
- **Canvas, not DOM rain.** Each rain column tracks one `drops[i]` integer and overwrites itself every frame. A DOM-element-per-glyph approach would have hammered React/the GPU at 60fps for ~500 elements; canvas is one draw call per column. Trailing fade is achieved with `fillStyle = "rgba(5, 7, 9, 0.08)"` overlay each frame — the classic Matrix trick. dpr capped at 2 so 4K displays don't tank.
- **sessionStorage, not localStorage**, for the launch trigger. The intent is *"play once when the user just authed"*, not *"play once ever"*. sessionStorage clears on tab close, so closing → reopening the tab plays it again (which is what the user wanted — the moment is part of the brand). localStorage would make it feel one-shot-then-never-again.
- **Skip-on-keypress with a 150ms grace.** A 0ms grace meant any held key during auth redirect (Enter, etc.) would dismiss before the animation even started. 150ms is below human perception of delay but long enough to dodge the trailing keypress from the redirect bounce.
- **Boot lines as art, not data.** They claim "[ OK ] arming destructive interlock" etc. — these are accurate statements about what the backend actually does on startup, not invented copy. Brand-truth, not brand-fiction.

### Verification
- Playwright screenshot at `t=1400ms` showed: rain rendering, brand mark + tagline visible, 4 boot lines printed, "press any key to skip" hint at the bottom. Cyan-on-midnight contrast clean.
- Sign-in screenshot confirms the new button copy rendering at 1920px without truncation.
- 90/90 backend pytest still green (no backend change in this entry — included to prove nothing tangentially regressed).
- ESLint clean on the four touched files.

### Pitfalls / lessons (read me, future agent)
- **Don't ship a click-anywhere-to-skip without a grace period.** The first iteration I wrote did exactly that. The auth redirect from `/auth/callback` to `/ide` arrives with focus on the document, and any in-flight key event (especially Enter from Google's "Confirm" click) immediately kills the animation. 150ms was the smallest grace that survived every browser I tried.
- **`requestAnimationFrame` cleanup is non-negotiable** in this component. If the user navigates away mid-rain (or the parent unmounts during fade), `cancelAnimationFrame(rafRef.current)` plus the resize listener removal must both fire. The `useEffect` cleanup handles this — don't refactor it into a single combined effect without preserving both cleanups.
- **The brand button is now ~46 chars.** If you ever add a country/locale variant ("INICIA SUSTRATO DE DESARROLLO AUTÓNOMO"), wrap-test on mobile (<360px). The current `tracking-[0.15em]` is already snug.
- The launch sequence intentionally renders OVER the IDE skeleton (z-100). That means the IDE has time to mount and fetch behind it, so when the curtain drops the workspace is fully hydrated. Don't move it to a separate route — you'd lose that priming.

### Next
- Consider an **AGENT MODE INTRO** card on first-ever sign-in (one-time) that explains the J persona + safety model. The launch sequence is now the visual onboarding; an information-layer companion would complete the loop. P2.
- The `propose_chronicle_entry` tool is still unstarted. Pick that up next session. P1.
- E2E Code Integrity Gateway verification via `testing_agent_v3_fork` is the oldest open ticket (since 2026-06-26). Highest priority — every other session keeps deferring it. **Stop deferring.** P0.

---

## 2026-06-28 03:00 UTC · File-tree right-click + inline rename + multi-HTML Live Preview — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
- Files were only renameable by deleting + re-creating. User explicitly asked for "manually editable files" which was correctly interpreted as inline rename.
- Live Preview hard-coded `index.html` — multi-page projects (e.g. anything with `pages/about.html`) had no preview path at all.
- The tree exposed actions via hover icons only. No right-click affordance — non-discoverable for anyone coming from VS Code / JetBrains IDEs.

### How we fixed it
- **Backend**: added `POST /api/projects/{id}/file/rename` (path-traversal-safe via `safe_join`, 404 on missing source, 409 on conflict, returns `is_dir`) and `POST /api/projects/{id}/mkdir` (creates empty folders, refuses to overwrite). Both in `routes/projects.py`.
- **New `frontend/src/components/ContextMenu.jsx`** — viewport-clamped (auto-reposition if overflow), Esc + outside-click dismiss, supports dividers + icons + danger styling + keyboard shortcut hints. Reusable for any panel that needs a right-click menu.
- **`FileTree.jsx` rewrite**: right-click menu items (Open · New file… · New folder… · Rename (F2) · Copy path · Download · Delete). Double-click row → inline rename input with extension auto-skipped during select. Open tabs auto-track renamed paths via new `onRenamed(oldPath, newPath, isDir)` callback wired in `IDE.jsx`. Empty-area right-click yields root-level menu (New file/folder/Upload/Refresh).
- **`LivePreview.jsx` rewritten**: accepts `htmlFiles` + `initialPath` props. Header has dropdown listing every `.html` file in the project (recursive walk via `useMemo` in IDE.jsx, `index.html` bubbled to top). Selection priority: explicit override → active editor tab if HTML → `index.html` → first HTML found. Friendly empty-state + inline error rendering.

### Why we fixed it that way
- **`safe_join` on BOTH src and dst** in the rename endpoint. Almost shipped it with only the source guarded, which would have let `{old_path: "main.py", new_path: "../escape.md"}` write outside the workspace. Verified the path-traversal block with curl.
- **`onRenamed` callback bubbling, not refetch**. When you rename, the tree refetches (cheap) but the open tabs need their `path` field updated so the editor still saves to the right place. Re-deriving tabs from tree would lose dirty-state / cursor position. The callback updates the tabs in-place and re-keys `activeTab`.
- **Dropdown for HTML selection, not a free-text input**. A free-text input invites typos and gives no discovery. The dropdown is the actual source of truth from the tree, so users can ONLY pick something that exists.
- **Right-click on empty area shows root-level menu**, not nothing. Discoverability — a user who right-clicks below the last file should still get "New file…" without having to find the toolbar icon.

### Verification
- Curl-tested conflict, missing-source, and path-traversal cases — all returned correct error codes (409, 404, 400).
- Playwright screenshot showed context menu rendering with all 8 items + dividers, AND the multi-HTML dropdown listing `index.html` + `pages/about.html` after we created the latter via API.
- 90/90 backend pytest still green.

### Pitfalls / lessons
- **`forwardRef` import was originally placed mid-file, below other top-level statements.** ES modules don't tolerate that (it works in webpack hot-reload but blows up in production build). Moved to the top of the file. Future agent: never place `import` statements anywhere except the very top.
- **Phosphor icons are tree-shaken by named import.** Don't write `import * as Icons` — bundle size jumps ~80KB. The pattern in `FileTree.jsx` (explicit named list) is correct.

### Next
- Drag-and-drop file move in the tree (visual cousin of rename — same backend endpoint).
- Live Preview relative-asset support via `<base>` injection or proxy serving.

---

## 2026-06-26 23:00 UTC · Backend monolith split (server.py 2,314 → 77 lines) — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
`backend/server.py` had crossed 2,314 lines. Routes, helpers, LLM chain, WebSocket PTY, chronicle helpers, GitHub integration, file CRUD — all in one file. Symptoms: J couldn't read the full file in one context window. Hot reload was sluggish. Adding a new route forced editing the same monolithic module every time, increasing merge conflict risk for the upcoming OAuth work.

### How we fixed it
Split into focused modules:
- `server.py` (77 lines) — pure FastAPI app shell: mount routers, CORS, startup/shutdown.
- `deps.py` — DB client, `get_current_user`, project paths, `safe_join`, `consume_override`, `detect_language`, `seed_project`, `user_from_token` (the WS-friendly variant).
- `llm_chain.py` — `TASK_CHAINS` dict, `resolve_byok`, `_call_ollama`, `_single_call`, `chain_call` (with Private-Mode filter and telemetry recording).
- `chronicle_helpers.py` — `chronicle_session_start` (idempotent) and `chronicle_narrative` (J-voiced session_end writer).
- `routes/*.py` — `auth`, `projects`, `gauntlet`, `terminal` (HTTP exec + WS PTY together), `git_local`, `settings`, `chronicle`, `ai`, `github`, `audit`, `uploads`, `agents`.

### Why we fixed it that way
- **Per-concern, not per-HTTP-method.** Tempting to split into `routes/get.py`, `routes/post.py` — would have been disastrous. Tracing a feature would require touching every file. The current shape: one file owns one product concern. Find a bug? Open one file.
- **Shared helpers at `/app/backend/` root, not inside `routes/`.** Otherwise route modules would import each other → circular import risk. The rule: helpers flow DOWN to routes, routes never import sibling routes.
- **WebSocket stayed on `app`, not the API router.** `APIRouter.websocket()` exists but the kube ingress was already set up for the `app`-level binding and changing it risked breaking the PTY terminal. `terminal.register_ws(app)` keeps that working unchanged.
- **chronicle helpers extracted to a top-level module**, not into `routes/chronicle.py`, because `routes/ai.py` (the agent loop) needs them too. Routes-importing-routes would loop.

### Verification
- 90/90 backend pytest pass post-refactor. One test (`test_http_exec_timeout_is_300`) needed its file-path target updated from `server.py` to `routes/terminal.py` (static source grep test) — this is the kind of thing to expect when relocating code.
- API surface unchanged: tested `/api/auth/me`, `/api/projects`, `/api/ai/chain`, `/api/terminal/exec` (via curl) — same responses byte-for-byte.

### Pitfalls / lessons
- **Tests that grep the source file path are fragile.** They tripped the moment we moved code. Either inline-grep the new path, or replace the test with a behavioral check (call the endpoint, verify the timeout). I patched the path; a future agent should consider the behavioral rewrite.
- **`load_dotenv()` must run before any module that reads `os.environ[...]` at import time.** `deps.py` does the `load_dotenv` at module import. Don't reorder the imports in `server.py` so that, say, `routes.ai` runs first — `EMERGENT_LLM_KEY` will KeyError.

### Next
- `routes/ai.py` is now the longest module (443 lines). If it grows further, extract the agent loop body to `routes/ai_agent.py`.

---

## 2026-06-26 14:30 UTC · Code Integrity Gateway — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
User reported (with emphasis: "lives could be at stake") that J was:
1. Truncating files mid-write with comments like `# ...rest of file unchanged...` — corrupting working code.
2. Writing syntactically broken Python that crashed the runtime on next exec.

Both failures were silent. The `write_file` tool returned `{ok: true}` and J moved on, never knowing the file was now wrong.

### How we fixed it
New `core/code_integrity.py` — deterministic pre-write validator:
- **Truncation regex bank**: matches `...`, `# rest`, `// rest`, `# unchanged`, `// unchanged`, `# TODO: complete`, etc. (case-insensitive, anchored to line-leading whitespace to avoid false positives in legitimate prose).
- **Bracket balance check**: stack-walks `()`, `[]`, `{}` accounting for string literals and comments.
- **Python AST parse**: for `.py` files, runs `ast.parse(content)` — any `SyntaxError` rejects the write.
- Wired into `core/tools.py` `write_file` AND `append_file`. Rejection returns `{error: "INTEGRITY_HALT: ..."}` which bounces back into the agent loop as a tool error — J MUST regenerate the full file.

### Why we fixed it that way
- **Deterministic, not LLM-judged.** A second LLM call to "review" the write would itself hallucinate. Regex + AST are deterministic; they have known false-positive modes I can document.
- **Pre-write, not post-write.** Post-write would mean the broken file already touched disk and could be picked up by hot-reload before we noticed. Pre-write is atomic from the caller's POV.
- **Both `write_file` AND `append_file`.** Append was originally unguarded; J would `append "..."` and corrupt the end of a file. Now both go through the gateway.
- **No override flag.** User was explicit: deterministic. No mechanism to bypass — if J needs to write `...` literally, it must escape it in a string.

### Verification
- Unit-tested via bash script: 8 truncation strings rejected, 4 legitimate file contents accepted, 3 Python syntax errors rejected, 1 unbalanced-bracket case rejected.
- E2E through the agent loop **still pending** — that requires `testing_agent_v3_fork`. **Carrying this debt forward.**

### Pitfalls / lessons
- **The truncation regex anchored on `^\s*\.\.\.$` (a line that is just `...`).** First draft also flagged inline `...` inside type annotations (`Callable[..., Any]`) and ellipsis literals (`def stub(): ...`). Anchor-to-line-boundary was the fix. If you tighten this regex further, run it against `core/` itself first — there's a `def stub(): ...` somewhere that will catch you out.
- **AST parse is Python-only.** JS/TS files only get the bracket check + truncation check. Adding tree-sitter for JS/TS would be the right upgrade but is heavier than this session's scope.

### Next
- **E2E verification via `testing_agent_v3_fork`** — overdue. The current implementation has zero proof that the rejection-error round-trips correctly through the LLM chain to J.

---

## 2026-06-26 02:00 UTC · Chat persistence + END SESSION + email transcripts — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
Switching AI tabs (Chat → Refine → Gauntlet) unmounted the chat sub-tree. Came back to the Chat tab → empty. Lost conversation history, lost scroll position, lost the half-typed message in the textarea.

### How we fixed it
- Chat state lifted from `ChatTab` into `AICoworker` parent. All four tabs render simultaneously; non-active ones get `className="hidden"` (CSS, not unmount). Conversation, scroll, textarea — all preserved.
- New **END SESSION** button (right side of chat toolbar, disabled until ≥1 user message). Click → `POST /projects/{id}/chronicle/close-session` which pulls messages from `db.messages`, writes a `session_end` chronicle entry via J's voice, and (if opted in) emails the transcript via Resend.
- New endpoints `GET/POST /me/email-prefs` storing `email_transcripts_enabled` + `transcript_email_address` per user.
- `core/email.py` uses `asyncio.to_thread(resend.Emails.send, …)` to avoid blocking the event loop. Sender preference: `RESEND_FROM_PREFERRED=j@bluejgenesis.com` with fallback to `onboarding@resend.dev` when the preferred domain isn't yet DNS-verified.

### Why we fixed it that way
- **`hidden` class, not conditional render.** React unmounts on `{cond && <ChatTab />}`. Even React's `<Tabs>` from many UI libs do this. Only `display:none` preserves the DOM subtree (and its child state).
- **opt-in email, default off.** Quiet by default. The transcript can contain sensitive code — never send without explicit opt-in.
- **Resend, not SMTP.** Existing Emergent infra is HTTP-API-friendly. SMTP would have meant managing TLS, queueing, and bounce-handling ourselves.

### Verification
Manual: signed in, ran a chat, hit END SESSION, confirmed `session_end` chronicle entry appeared with J's narrative and the email arrived.

### Pitfalls / lessons
- **Don't `await` synchronous Resend SDK calls directly.** Blocks the FastAPI event loop. Wrap in `asyncio.to_thread`.
- **DNS verification for custom sender domains is async** — Resend won't tell you the domain is unverified until you actually try to send. The graceful fallback to the default verified sender is what saves the user experience.

---

## 2026-06-25 19:00 UTC · Resizable panels + Chronicle filters + Folder zip — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
- IDE layout was 4 fixed columns. On a 13" laptop the editor was squeezed to ~250px. User complained: "the code editor is squeezed to a tiny sliver."
- The LOG tab and CHRONICLE tab were redundant; LOG only showed tool calls, Chronicle showed everything. Confusing.
- Tree only allowed downloading the entire project as zip — no way to grab a single subfolder.

### How we fixed it
- `react-resizable-panels` v4 wired into `IDE.jsx`. Horizontal `PanelGroup` with left tree / center editor / right AI. Terminal height handled separately via a custom drag handle persisted in `localStorage`. Library quirks: numeric `size` = px, strings = percent; don't wrap `<Panel>` children in extra flex containers.
- Removed standalone LOG tab. Tool calls now mirror into chronicle as `kind="tool"` entries. Chronicle UI gained: debounced (200ms) full-text search, per-signer chips (J / USER / SYSTEM), per-kind chips with live counts, reset-filters button.
- Tree hover toolbar gains an Archive icon on every folder row → backend endpoint `GET /projects/{id}/download_zip?path=<folder>` returns the subfolder as zip with internal paths rooted at the folder name.

### Pitfalls / lessons
- **`react-resizable-panels` is fussy about parent flex.** Initially the editor was 0px wide because I had `flex-col` on a Panel. The library does its own layout — don't fight it.
- **Bearer-token blob downloads require axios `responseType: 'blob'`** — a plain `window.open()` strips the Authorization header on mobile, where there's no cookie. Used the axios-based downloader instead.

---

## 2026-06-25 14:00 UTC · Chronicle (flight-recorder) — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
Sessions had no audit trail. If J shipped a fix, there was no court-grade proof of what was done, when, by whom, in what order. The user's stance: this is non-negotiable for the trust model.

### How we fixed it
- Mongo collection `chronicle_entries` with compound index `(project_id, ts_ns)` — append-only.
- SHA-256 hash chain: each entry's `entry_hash = sha256(prior_hash + serialized_payload)`. Tampering with any past entry breaks the chain forward.
- Atomic disk mirror at `.gauntlet/chronicle.md` + `.gauntlet/sessions/<id>.md`. Write-tmp + fsync + rename, never partial writes.
- Auto `session_start` on first chat message; auto `session_end` narrative in J's voice via new `CHRONICLE_PROMPT`.
- Endpoints: `GET /chronicle`, `POST /chronicle/entry`, `GET /chronicle/sessions`, `GET /chronicle/verify` (walks the hash chain), `GET /chronicle/export` (returns full markdown).
- UI: dedicated CHRONICLE tab with session pills, signer-icon entry cards (Robot / User / Scroll per signer), manual entry form.

### Why we fixed it that way
- **Mongo + disk, both.** Mongo is the queryable source of truth. Disk is the human-readable fallback in case Mongo dies. The disk write must be atomic (tmp + rename) so a power loss can't corrupt the file.
- **SHA-256 hash chain, not signatures.** Signatures would require key management — out of scope. The hash chain detects tampering with high confidence and zero infrastructure.

### Pitfalls / lessons
- **`ts_ns` (nanosecond integer) is the sort key**, not `ts` (ISO string). Two entries written in the same millisecond would otherwise have indistinguishable order.

---

## 2026-06-25 09:00 UTC · Local Monaco + Terminal cleanup + Destructive bash trap — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
- Monaco loaded from CDN. Production-deploy environments without outbound HTTPS to CDNs broke the editor.
- WS PTY shell counter leaked when the client disconnected mid-session (counter incremented but never decremented).
- The destructive-code interlock was UI-only — a user running `rm -rf /` directly in the terminal still got blocked at the WS layer, but the trap was duplicated across multiple subprocesses inconsistently.

### How we fixed it
- `monaco-editor` bundled locally via Webpack 5 `new URL(..., import.meta.url)` for worker URLs + `loader.config({ monaco })` for the API. Zero CDN dependence.
- WS pump: `asyncio.wait(FIRST_COMPLETED, {pty_task, ws_task})` — as soon as EITHER side disconnects, both get torn down and the counter decrements in the `finally` block.
- In-shell bash DEBUG trap with `shopt -s extdebug` blocks `rm -rf /|~|/*|.|..`, `mkfs.*`, `dd of=/dev/{sd,nvme,hd,mmc}*`, `:(){:|:&};:`, and `chmod -R 777 /` at the bash level itself. Depth-guard ensures the trap only fires on top-level interactive commands, not helper functions inside scripts.

### Pitfalls / lessons
- **Monaco's worker URLs are NOT relative-resolvable** through standard Webpack import — must use `new URL(..., import.meta.url)`. The CRA + craco config in `craco.config.js` does this. Don't touch it.
- **bash `extdebug` is per-shell**, not inherited. If a user `exec bash` mid-session the trap is lost. Mitigated by always opening a fresh PTY with the trap pre-installed.

---

## 2026-06-19 21:00 UTC · Private Mode — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
For sensitive code, the user needed a way to guarantee NO cloud LLM ever sees the project — Universal Key included. The fallback chain ran cloud first by default.

### How we fixed it
- One-click `PUBLIC ↔ PRIVATE` pill in the TopBar (Lock / LockOpen icon, cyan glow when active).
- Backend: `_chain_call` checks `user.private_mode` and filters the chain to `provider == "ollama"` only.
- `GET /api/ai/chain` reports cloud steps as `runnable: false` when PRIVATE is on. UI updates the Resolved Chain panel live.
- New endpoints `GET/POST /api/me/private-mode`. POST refuses to enable when no local server is linked (`400` with a clear message).

### Pitfalls / lessons
- **Don't let the user enable Private Mode without a configured local server** — they'd hit a "chain exhausted, no providers runnable" error on the next message. The 400 guard prevents the trap.

---

## 2026-06-19 14:00 UTC · Mobile OAuth fix + Ollama BYOK + 9-step Tutorial — signed: J (Claude Sonnet 4.5 via Universal Key)

### What broke
Android Chrome blocks third-party cookies on cross-origin OAuth bounces → infinite redirect loop on sign-in. iOS Safari worked fine, desktop worked fine, Android Chrome users were dead-locked at the login page.

### How we fixed it
- `/api/auth/session` now returns `session_token` in the JSON body AND sets the cookie. Frontend stores in `localStorage` under `gauntlet_session_token`.
- Axios request interceptor attaches `Authorization: Bearer <token>` on every call.
- `get_current_user` falls back to the Bearer header when the cookie is absent.
- `AuthCallback` now uses `window.location.replace('/ide')` (hard navigate, not React Router) to dodge the React state race that was bouncing mobile users back to `/login`.
- `AuthCallback` extracts `session_id` from BOTH URL hash AND query string — some Android Chrome redirect chains strip the fragment.

### Pitfalls / lessons
- **Never use React Router `navigate()` after a successful auth exchange.** The AuthProvider hasn't re-run `/me` yet, so the `<RequireAuth>` wrapper sees `user === null` and redirects you back to `/login`. Hard navigate (`window.location.replace`) forces a full mount cycle.
- **`Authorization` header is stripped by some kube ingresses on OPTIONS preflight.** Verified ours doesn't, but if you're debugging a similar issue elsewhere, check the ingress config first.

---

## 2026-05-23 · MVP — Gauntlet DevSpace v1 — signed: J (Claude Sonnet 4.5 via Universal Key)

Initial substrate. Sovereign Shards branded shell. Monaco + xterm + AI Coworker (Chat/Refine/Gauntlet/Logs) + Five Masters AST + Destructive interlock with password override + Emergent Google OAuth + LLM failover chain (Universal first, then BYO). Tagline: **DETERMINISTIC. AUTONOMOUS. SUBSTRATE.**
