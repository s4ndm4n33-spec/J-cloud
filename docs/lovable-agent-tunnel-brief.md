# Lovable Brief — Agent Tunnel Dashboard

Paste this whole document as the initial Lovable prompt. It's calibrated to
yield a working dashboard on the first pass. Don't split it up — Lovable
reads it as a single design brief.

---

## Product context

Build a **standalone read-and-act dashboard** for the "Agent Tunnel" —
a ticket bus between two deployments of an AI coding agent named J
(prev-J on preview, prod-J on production). Tickets flow via HTTP to a
FastAPI backend hosted at `https://blue-j-gauntlet.com`. Only the owner
can view or act on tickets. This dashboard exists because we currently
have no UI to see what the two Js are proposing to each other — it's
all curl.

**Users**: exactly one — the app owner. No signup / multi-tenant. Auth is
a single Bearer token pasted into the settings sheet.

**Core loop**:
1. Prod-J files a ticket (bug or fix proposal) via her own tools
2. Ticket appears in this dashboard's inbox
3. Owner reads it, optionally previews the diff
4. Owner either lets prev-J apply it (button here), or rejects, or escalates
5. Owner sees status update on next 30s poll

---

## Design language — MATCH IT PRECISELY

This dashboard is a companion to Gauntlet DevSpace. Use the same visual
system so it feels native when opened next to the main app:

- **Background**: `#0a0e1a` (near-black midnight blue)
- **Panels**: `#0f1420` with `1px solid rgba(0,217,255,0.15)` borders
- **Primary accent**: cyan `#00d9ff` (borders on hover, primary buttons,
  active tabs)
- **Warning accent**: amber `#fbbf24` (escalate flags, p1 tickets)
- **Critical accent**: red-400 `#f87171` (rejected status, p0, delete)
- **Alloy / muted text**: `#7a8899`
- **White text**: `#e7ecf1` (gridwhite)
- **Fonts**: `Inter` for body, `JetBrains Mono` for IDs / status codes / diffs
- **Aesthetic**: HUD / terminal / spaceship-command-console. Uppercase
  tracking-widest labels. `//` prefix for hint text. Corner tick marks
  on hero panels. No rounded corners on primary elements — sharp edges.
- **Buttons**: bordered outline style, no fill. Hover fills with 10%
  accent alpha. Font: display uppercase 10-11px tracking-widest.
- Do NOT use purple/violet gradients. Do NOT use rounded soft-UI cards.

Reference emoji-free vibe: think Alien: Isolation UI, or Death Stranding's
odradek terminal. Not shadcn defaults.

---

## Screens

### 1. Inbox (default view)
- Left rail: filter tabs — ALL · OPEN · IN PROGRESS · READY FOR DEPLOY ·
  DEPLOYED · REJECTED · ESCALATED (badge count on each)
- Main pane: table/list of tickets, newest first. Each row shows:
  - `ticket_id` (mono, small, click-to-copy)
  - `from → to` (e.g. "prod-j → prev-j")
  - `kind` chip (bug/proposal/reply/question)
  - `priority` chip (p0 red / p1 amber / p2 alloy)
  - `title` (bold, single line, truncated)
  - `status` chip (color-coded)
  - `escalate` warning icon if `escalate === true`
  - relative timestamp (e.g. "3m ago")
- Row click → opens ticket detail

### 2. Ticket detail
- Full body rendered as markdown
- Metadata sidebar: from, to, kind, priority, status, escalate, created ts,
  updated ts, parent_ticket_id (linked)
- Files touched: list of paths
- `code_diff` block: render with syntax highlighting (unified diff format,
  `+` lines green tint, `-` lines red tint, headers alloy). Copy button.
- History timeline at bottom: every entry from `history[]` array —
  {role, action, ts, note}. Vertical timeline, most recent at top.
- Action buttons (owner-only, all of them are for owner):
  - **APPLY** (only visible if `to === "prev-j"` and status is `open` or
    `in_progress` and `!escalate`) — POST `/api/agent-tunnel/tickets/{id}/apply`
    with body `{"run_tests": false}`. Show a spinner; on 200, refresh detail.
  - **REPLY** — opens a textarea + optional diff field. POST `/reply`
  - **MARK IN PROGRESS** / **MARK REJECTED** — POST `/status` with body
    `{"status": "in_progress" | "rejected"}`
  - **ESCALATE** — POST `/escalate` with body `{"reason": "..."}`.
    Confirmation modal — "This flags the ticket for human review and blocks
    apply until cleared. Sure?"
  - **FORCE SYNC** (small, in the header) — POST `/api/agent-tunnel/sync`

### 3. Timeline (secondary tab in top nav)
- Reverse-chron feed of ALL ticket history entries across ALL tickets
  (last 100). Each row: ts · ticket_id · role · action · note
- No API for this yet — for now derive client-side: fetch all tickets,
  flatten their history[] arrays, sort by ts desc, slice(100). Note in
  the brief: "TODO: replace with `GET /api/agent-tunnel/timeline` when
  backend ships it."

### 4. Settings sheet
- Text input for `apiBaseUrl` (default `https://blue-j-gauntlet.com`)
- Text input for `ownerToken` (Bearer)
- Persist both to localStorage
- Test connection button → GET `/api/agent-tunnel/whoami`, show
  `{role, self}` on success

---

## API contract — the ONLY endpoints this app should touch

Base URL: value of `apiBaseUrl` setting. Every request needs header
`Authorization: Bearer ${ownerToken}`. Content-Type `application/json` on
POST/PUT/DELETE bodies.

### Read

```
GET  /api/agent-tunnel/whoami
    → { role: "prev" | "prod", self: "prev-j" | "prod-j" }

GET  /api/agent-tunnel/tickets?to=&status=&limit=
    → { tickets: Ticket[], count: number, self: "prev-j" | "prod-j" }
    All query params optional. `to` filters to a specific recipient role.
    `status` filters to one of open|in_progress|ready_for_deploy|deployed|rejected.
    Default excludes deployed+rejected.

GET  /api/agent-tunnel/tickets/{ticket_id}
    → Ticket
```

### Write

```
POST /api/agent-tunnel/tickets
    body: { to, kind, title, body, code_diff?, files_touched?, priority?,
            parent_ticket_id? }
    to        : "prev-j" | "prod-j" | "user"
    kind      : "bug" | "proposal" | "reply" | "question"
    priority  : "p0" | "p1" | "p2"   (default p1)
    → { ok: true, ticket: Ticket }

POST /api/agent-tunnel/tickets/{ticket_id}/reply
    body: { body, code_diff? }
    → { ok: true, reply_ticket_id: string }

POST /api/agent-tunnel/tickets/{ticket_id}/status
    body: { status, note? }
    status: "open" | "in_progress" | "rejected"
    (ready_for_deploy and deployed cannot be set from the dashboard;
     they come from apply_diff or from prod's redeploy)
    → { ok: true, status }

POST /api/agent-tunnel/tickets/{ticket_id}/escalate
    body: { reason }
    → { ok: true, escalated: true }

POST /api/agent-tunnel/tickets/{ticket_id}/apply
    body: { run_tests: boolean }         # default false
    → { ok: true, applied: true, paths: string[], loc: number, tests_ran: bool }
    Errors return 400 with detail; render the detail as a red panel.

POST /api/agent-tunnel/sync
    → { ok: true, pulled: number, keys_seen: number }
```

### Ticket schema

```ts
interface Ticket {
  ticket_id: string;                  // "tkt_<12hex>"
  from: "prev-j" | "prod-j" | "user";
  to:   "prev-j" | "prod-j" | "user";
  kind: "bug" | "proposal" | "reply" | "question";
  title: string;                      // max 200
  body: string;                       // markdown-ish, max 20000
  code_diff: string | null;           // unified diff
  files_touched: string[];
  status: "open" | "in_progress" | "ready_for_deploy" | "deployed" | "rejected";
  parent_ticket_id: string | null;
  priority: "p0" | "p1" | "p2";
  created_by: string;
  ts: string;                         // ISO8601
  updated_ts: string;                 // ISO8601
  history: Array<{
    role: string;
    action: string;                   // "opened" | "replied" | "status:xxx" | "escalated"
    ts: string;
    note: string | null;
  }>;
  escalate: boolean;
}
```

---

## Polling & real-time

- Inbox list: poll `GET /api/agent-tunnel/tickets` every 30s
- Detail view: poll `GET /api/agent-tunnel/tickets/{id}` every 15s while open
- Show a small "last synced Xs ago" indicator in the header
- Manual "FORCE SYNC" button hits `POST /api/agent-tunnel/sync` which
  makes the backend pull fresh tickets from R2 immediately

## Error handling
- 401 → prompt user to open settings and paste a valid Bearer
- 403 → show "owner only — this token isn't the owner's" red banner
- 400/500 on POST → show the response's `detail` field verbatim in a
  toast (they're already human-readable — e.g. "diff touches denied paths: [...]")
- Network errors → grey "offline" indicator in header

## Non-goals for MVP
- No mobile layout — this is a desktop-only console
- No search / full-text
- No pagination — inbox is capped server-side at 30 tickets, that's fine
- No user management — single owner, single token
- No diff editing in-app — diffs are read-only; edits happen by REPLY with
  a corrected diff

---

## Tech stack (Lovable's defaults are fine)
- React + Vite
- Tailwind + shadcn (customize the color palette per the design language above)
- react-router (Inbox / Detail / Timeline / Settings)
- No state management library needed — plain useState + a small
  `useTunnelClient()` hook that wraps fetch
- Deploy to Lovable's default host; keep the URL private (share only with
  yourself)

## First-pass acceptance criteria
- I can paste a Bearer token in Settings, click Test Connection, and see
  `{role, self}` come back
- Inbox loads and shows my open tickets with correct color coding
- Clicking a ticket opens the detail view
- APPLY button on a `to: prev-j` ticket triggers `/apply` and I see the
  status update within 15s
- ESCALATE button asks for a reason and posts it correctly
- The whole thing looks like it belongs next to a NASA console

Ship a working v1. Polish comes in v2.
