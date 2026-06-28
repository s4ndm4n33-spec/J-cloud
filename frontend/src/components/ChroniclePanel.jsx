import { useEffect, useMemo, useState } from "react";
import {
  Scroll, Download, ShieldCheck, Plus, ArrowsClockwise, X, Robot, User,
  CircleNotch, Funnel, MagnifyingGlass, Check, SkipForward, PencilSimple, Eye,
} from "@phosphor-icons/react";
import {
  listChronicle, listChronicleSessions, addChronicleEntry,
  verifyChronicle, exportChronicle, acceptChronicleProposal,
  skipChronicleProposal, readChronicleSnapshot,
} from "@/lib/api";

const SIGNER_COLORS = {
  J:      { fg: "var(--cyan)",     bg: "rgba(0,217,255,0.10)" },
  USER:   { fg: "var(--gridwhite)",bg: "rgba(231,236,245,0.06)" },
  SYSTEM: { fg: "var(--alloy)",    bg: "rgba(125,133,151,0.08)" },
};

function shortHash(h) { return (h || "").slice(0, 10); }

function snapshotPathFromTags(tags) {
  for (const t of tags || []) {
    if (typeof t === "string" && t.startsWith("file:.gauntlet/snapshots/")) {
      return t.slice(5);
    }
  }
  return null;
}

function EntryCard({ entry, projectId, onRefresh }) {
  const c = SIGNER_COLORS[entry.signer] || SIGNER_COLORS.SYSTEM;
  const Icon = entry.signer === "J" ? Robot : entry.signer === "USER" ? User : Scroll;
  const isProposed = entry.kind === "proposed" && !entry.proposal_status;
  const isSkipped = entry.proposal_status === "skipped";
  const isAccepted = entry.proposal_status === "accepted";
  const snapshotPath = snapshotPathFromTags(entry.tags);

  // Local UI state for snapshot inline render
  const [snapHtml, setSnapHtml] = useState(null);
  const [snapLoading, setSnapLoading] = useState(false);
  const [snapErr, setSnapErr] = useState(null);

  // Local UI state for accept-with-edit
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(entry.title);
  const [editBody, setEditBody] = useState(entry.body || "");
  const [busy, setBusy] = useState(false);

  async function toggleSnapshot() {
    if (snapHtml !== null) { setSnapHtml(null); return; }
    if (!snapshotPath) return;
    setSnapLoading(true); setSnapErr(null);
    try {
      const r = await readChronicleSnapshot(projectId, snapshotPath);
      setSnapHtml(r.content || "");
    } catch (e) {
      setSnapErr(e?.response?.data?.detail || "Could not load snapshot");
    } finally { setSnapLoading(false); }
  }

  async function accept(viaEdit = false) {
    setBusy(true);
    try {
      await acceptChronicleProposal(projectId, {
        entry_hash: entry.entry_hash,
        ...(viaEdit ? { title: editTitle, body: editBody } : {}),
      });
      onRefresh?.();
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Accept failed");
    } finally { setBusy(false); setEditing(false); }
  }

  async function skip() {
    if (!window.confirm("Skip this proposed chronicle entry?")) return;
    setBusy(true);
    try {
      await skipChronicleProposal(projectId, entry.entry_hash);
      onRefresh?.();
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Skip failed");
    } finally { setBusy(false); }
  }

  return (
    <div
      className={`border-l-2 px-3 py-2 ${
        isProposed ? "border-dashed outline outline-1 outline-cyan/30" : ""
      } ${isSkipped ? "opacity-50" : ""}`}
      style={{ borderColor: c.fg, background: c.bg }}
      data-testid={`chronicle-entry-${entry.entry_id}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon size={11} style={{ color: c.fg }} weight="fill" />
        <span className="font-mono text-[0.65rem]" style={{ color: c.fg }}>{entry.signer}</span>
        <span className="font-mono text-[0.6rem] text-alloy/70">{entry.kind}</span>
        {isProposed && (
          <span className="font-mono text-[0.55rem] text-cyan px-1.5 py-0.5 border border-cyan/40 tracking-wider">
            // PROPOSED · NEEDS YOUR CALL
          </span>
        )}
        {isSkipped && (
          <span className="font-mono text-[0.55rem] text-alloy px-1.5 py-0.5 border border-alloy/30 tracking-wider">
            // SKIPPED
          </span>
        )}
        {isAccepted && (
          <span className="font-mono text-[0.55rem] text-cyan/70 px-1.5 py-0.5 border border-cyan/20 tracking-wider">
            // ACCEPTED
          </span>
        )}
        <span className="font-mono text-[0.6rem] text-alloy ml-auto">{entry.ts_iso?.slice(0, 19).replace("T", " ")}</span>
        <span
          className="font-mono text-[0.55rem] text-alloy/50"
          title={`hash ${entry.entry_hash}\nprior ${entry.prior_hash}`}
        >{shortHash(entry.entry_hash)}</span>
      </div>

      {editing ? (
        <>
          <input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            className="w-full bg-midnight border border-cyan/30 px-2 py-1 mb-2 font-display text-[0.8rem] text-gridwhite"
            data-testid={`chronicle-edit-title-${entry.entry_id}`}
          />
          <textarea
            rows={4}
            value={editBody}
            onChange={(e) => setEditBody(e.target.value)}
            className="w-full bg-midnight border border-cyan/30 px-2 py-1 font-mono text-[0.7rem] text-gridwhite resize-none"
            data-testid={`chronicle-edit-body-${entry.entry_id}`}
          />
        </>
      ) : (
        <>
          <div className="font-display text-[0.8rem] text-gridwhite tracking-[0.05em] mb-1">{entry.title}</div>
          {entry.body && (
            <div className="font-mono text-[0.7rem] text-gridwhite/80 leading-relaxed whitespace-pre-wrap">
              {entry.body}
            </div>
          )}
        </>
      )}

      {(entry.tags || []).length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap">
          {entry.tags.map((t, i) => (
            <span key={i} className="font-mono text-[0.55rem] text-cyan/80 border border-cyan/30 px-1.5 py-0.5">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Snapshot expand/collapse */}
      {snapshotPath && (
        <div className="mt-2">
          <button
            onClick={toggleSnapshot}
            disabled={snapLoading}
            data-testid={`chronicle-snapshot-toggle-${entry.entry_id}`}
            className="flex items-center gap-1 font-mono text-[0.65rem] text-cyan hover:text-gridwhite border border-cyan/30 hover:border-cyan px-2 py-1 transition-colors"
          >
            <Eye size={11} />
            {snapLoading ? "loading…" : snapHtml === null ? "VIEW SNAPSHOT" : "HIDE SNAPSHOT"}
          </button>
          {snapErr && <div className="mt-1 font-mono text-[0.6rem] text-orange">// {snapErr}</div>}
          {snapHtml !== null && (
            <div className="mt-2 border border-cyan/20 bg-steel" data-testid={`chronicle-snapshot-frame-${entry.entry_id}`}>
              <iframe
                title={`snapshot-${entry.entry_id}`}
                srcDoc={snapHtml}
                sandbox=""
                style={{ width: "100%", height: 280, border: 0, background: "#fff" }}
              />
            </div>
          )}
        </div>
      )}

      {/* Proposed-entry action bar */}
      {isProposed && (
        <div className="mt-3 flex items-center gap-2 pt-2 border-t border-cyan/15">
          {editing ? (
            <>
              <button
                onClick={() => accept(true)}
                disabled={busy}
                data-testid={`chronicle-accept-edited-${entry.entry_id}`}
                className="flex items-center gap-1 font-mono text-[0.65rem] text-midnight bg-cyan hover:bg-cyan/80 px-2 py-1"
              >
                <Check size={11} weight="bold" /> ACCEPT EDITED
              </button>
              <button
                onClick={() => setEditing(false)}
                className="font-mono text-[0.65rem] text-alloy hover:text-gridwhite px-2 py-1"
              >CANCEL EDIT</button>
            </>
          ) : (
            <>
              <button
                onClick={() => accept(false)}
                disabled={busy}
                data-testid={`chronicle-accept-${entry.entry_id}`}
                className="flex items-center gap-1 font-mono text-[0.65rem] text-midnight bg-cyan hover:bg-cyan/80 px-2 py-1"
              >
                <Check size={11} weight="bold" /> ACCEPT
              </button>
              <button
                onClick={() => setEditing(true)}
                data-testid={`chronicle-edit-${entry.entry_id}`}
                className="flex items-center gap-1 font-mono text-[0.65rem] text-cyan border border-cyan/40 hover:border-cyan hover:bg-cyan/10 px-2 py-1"
              >
                <PencilSimple size={11} /> EDIT
              </button>
              <button
                onClick={skip}
                disabled={busy}
                data-testid={`chronicle-skip-${entry.entry_id}`}
                className="ml-auto flex items-center gap-1 font-mono text-[0.65rem] text-alloy hover:text-orange border border-alloy/30 hover:border-orange px-2 py-1"
              >
                <SkipForward size={11} /> SKIP
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function NewEntryForm({ projectId, sessionId, onAdded, onClose }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    const t = title.trim();
    if (!t) { setErr("title required"); return; }
    setBusy(true); setErr(null);
    try {
      await addChronicleEntry(projectId, {
        title: t, body: body.trim(),
        tags: tags.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 4),
        kind: "user_note", signer: "USER",
        session_id: sessionId || undefined,
      });
      setTitle(""); setBody(""); setTags("");
      onAdded?.();
      onClose?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || "save failed");
    } finally { setBusy(false); }
  }

  return (
    <div className="border border-cyan/30 bg-steel p-3 space-y-2" data-testid="chronicle-new-entry-form">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[0.7rem] text-cyan">// NEW ENTRY · signed USER</div>
        <button onClick={onClose} className="text-alloy hover:text-orange" data-testid="chronicle-new-cancel">
          <X size={11} weight="bold" />
        </button>
      </div>
      <input
        type="text"
        placeholder="title — what happened?"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="w-full bg-midnight border border-cyan/20 px-2 py-1 font-mono text-xs text-gridwhite"
        data-testid="chronicle-new-title"
      />
      <textarea
        rows={4}
        placeholder="body — context, decisions, gotchas (markdown ok)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        className="w-full bg-midnight border border-cyan/20 px-2 py-1 font-mono text-xs text-gridwhite resize-none"
        data-testid="chronicle-new-body"
      />
      <input
        type="text"
        placeholder="tags (comma-separated, e.g. bugfix, auth)"
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        className="w-full bg-midnight border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] text-gridwhite"
        data-testid="chronicle-new-tags"
      />
      {err && <div className="font-mono text-[0.65rem] text-orange">{err}</div>}
      <div className="flex justify-end gap-2">
        <button onClick={save} disabled={busy} className="btn-solid text-[0.7rem]" data-testid="chronicle-new-save">
          {busy ? <CircleNotch size={11} className="animate-spin" /> : null}
          COMMIT ENTRY
        </button>
      </div>
    </div>
  );
}

export default function ChroniclePanel({ project }) {
  const projectId = project?.project_id;
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);  // null = full
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [verify, setVerify] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [signers, setSigners] = useState({ J: true, USER: true, SYSTEM: true });
  // Default: narrative-first view (tool/log entries hidden until you ask)
  const [kinds, setKinds] = useState({
    session_start: true, session_end: true, narrative: true,
    milestone: true, user_note: true, tool: false, proposed: true,
  });

  async function refresh() {
    if (!projectId) return;
    setLoading(true);
    try {
      const [sess, entriesResp] = await Promise.all([
        listChronicleSessions(projectId),
        listChronicle(projectId, selectedSession),
      ]);
      setSessions(sess.sessions || []);
      setEntries(entriesResp.entries || []);
    } catch (_e) {
      setEntries([]);
    } finally { setLoading(false); }
  }

  useEffect(() => { refresh(); }, [projectId, selectedSession]);

  // Debounce search query → 200ms
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim().toLowerCase()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (!signers[e.signer]) return false;
      if (!kinds[e.kind]) return false;
      if (debounced) {
        const hay = `${e.title || ""}\n${e.body || ""}\n${(e.tags || []).join(" ")}`.toLowerCase();
        if (!hay.includes(debounced)) return false;
      }
      return true;
    });
  }, [entries, signers, kinds, debounced]);

  const tally = useMemo(() => {
    const t = { signers: { J: 0, USER: 0, SYSTEM: 0 }, kinds: {} };
    for (const e of entries) {
      if (t.signers[e.signer] !== undefined) t.signers[e.signer]++;
      t.kinds[e.kind] = (t.kinds[e.kind] || 0) + 1;
    }
    return t;
  }, [entries]);

  async function runVerify() {
    if (!projectId) return;
    setVerify("checking");
    try {
      const r = await verifyChronicle(projectId);
      setVerify(r);
    } catch {
      setVerify({ ok: false, entries: 0, broken: [{ msg: "request failed" }] });
    }
  }

  async function doExport() {
    if (!projectId) return;
    await exportChronicle(projectId, selectedSession);
  }

  function toggleSigner(s) { setSigners((p) => ({ ...p, [s]: !p[s] })); }
  function toggleKind(k) { setKinds((p) => ({ ...p, [k]: !p[k] })); }
  function showOnlyTools() {
    setSigners({ J: true, USER: true, SYSTEM: true });
    setKinds({ tool: true });
  }
  function resetFilters() {
    setSigners({ J: true, USER: true, SYSTEM: true });
    setKinds({
      session_start: true, session_end: true, narrative: true,
      milestone: true, user_note: true, tool: false, proposed: true,
    });
    setQuery("");
  }

  if (!projectId) {
    return (
      <div className="p-4 font-mono text-[0.7rem] text-alloy" data-testid="chronicle-panel">
        // pick a project to view its chronicle.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" data-testid="chronicle-panel">
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-2 flex-wrap">
        <Scroll size={12} className="text-cyan" weight="fill" />
        <span className="font-display text-[0.65rem] tracking-[0.25em] text-cyan">CHRONICLE</span>
        <span className="font-mono text-[0.6rem] text-alloy">// flight recorder · hash-chained</span>
        <button
          onClick={refresh}
          title="Refresh"
          className="ml-auto text-alloy hover:text-cyan"
          data-testid="chronicle-refresh"
        ><ArrowsClockwise size={11} /></button>
        <button
          onClick={runVerify}
          title="Verify hash chain integrity"
          className="text-alloy hover:text-cyan"
          data-testid="chronicle-verify"
        ><ShieldCheck size={11} /></button>
        <button
          onClick={doExport}
          title={selectedSession ? "Export this session" : "Export full chronicle"}
          className="text-alloy hover:text-cyan"
          data-testid="chronicle-export"
        ><Download size={11} /></button>
        <button
          onClick={() => setShowForm(true)}
          title="Add a manual entry"
          className="text-cyan hover:text-gridwhite"
          data-testid="chronicle-new"
        ><Plus size={11} weight="bold" /></button>
      </div>

      {verify && verify !== "checking" && (
        <div
          className={`px-3 py-1.5 border-b font-mono text-[0.7rem] ${
            verify.ok ? "border-viridian/30 text-viridian bg-viridian/5"
                      : "border-orange/40 text-orange bg-orange/10"
          }`}
          data-testid="chronicle-verify-result"
        >
          {verify.ok
            ? `CHAIN OK · ${verify.entries} entries, no tampering detected`
            : `CHAIN BROKEN · ${verify.broken?.length || 0} corrupted entries`}
        </div>
      )}
      {verify === "checking" && (
        <div className="px-3 py-1.5 font-mono text-[0.7rem] text-cyan border-b border-cyan/20">
          walking hash chain…
        </div>
      )}

      {/* session picker */}
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-1 overflow-x-auto scrollbar-thin">
        <button
          onClick={() => setSelectedSession(null)}
          className={`font-mono text-[0.65rem] px-2 py-0.5 border whitespace-nowrap ${
            selectedSession === null
              ? "border-cyan text-cyan bg-cyan/10"
              : "border-cyan/20 text-alloy hover:text-cyan"
          }`}
          data-testid="chronicle-session-all"
        >ALL · {sessions.reduce((s, x) => s + x.count, 0)}</button>
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => setSelectedSession(s.session_id)}
            title={s.first_title || s.session_id}
            className={`font-mono text-[0.65rem] px-2 py-0.5 border whitespace-nowrap ${
              selectedSession === s.session_id
                ? "border-cyan text-cyan bg-cyan/10"
                : "border-cyan/20 text-alloy hover:text-cyan"
            }`}
            data-testid={`chronicle-session-${s.session_id}`}
          >
            {s.session_id.slice(-8)} · {s.count}
          </button>
        ))}
      </div>

      {/* search */}
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-2">
        <MagnifyingGlass size={11} className="text-alloy" />
        <input
          type="text"
          placeholder="search title, body, tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 bg-midnight border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] text-gridwhite"
          data-testid="chronicle-search"
        />
        {(query || Object.values(kinds).some((v) => !v) || Object.values(signers).some((v) => !v)) && (
          <button
            onClick={resetFilters}
            className="font-mono text-[0.6rem] text-alloy hover:text-cyan"
            data-testid="chronicle-reset-filters"
          >reset</button>
        )}
      </div>

      {/* filter chips */}
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-1 flex-wrap">
        <Funnel size={10} className="text-alloy mr-1" />
        <span className="font-mono text-[0.6rem] text-alloy mr-1">signer:</span>
        {["J", "USER", "SYSTEM"].map((s) => (
          <button
            key={s}
            onClick={() => toggleSigner(s)}
            className={`font-mono text-[0.6rem] px-1.5 py-0.5 border ${
              signers[s]
                ? "border-cyan text-cyan bg-cyan/10"
                : "border-alloy/30 text-alloy/50"
            }`}
            data-testid={`chronicle-filter-signer-${s}`}
          >{s} · {tally.signers[s] || 0}</button>
        ))}
        <span className="font-mono text-[0.6rem] text-alloy ml-2 mr-1">kind:</span>
        {Object.keys(kinds).map((k) => (
          <button
            key={k}
            onClick={() => toggleKind(k)}
            className={`font-mono text-[0.6rem] px-1.5 py-0.5 border ${
              kinds[k]
                ? "border-cyan text-cyan bg-cyan/10"
                : "border-alloy/30 text-alloy/50"
            }`}
            data-testid={`chronicle-filter-kind-${k}`}
          >{k.replace("_", " ")}{tally.kinds[k] ? ` · ${tally.kinds[k]}` : ""}</button>
        ))}
        <button
          onClick={showOnlyTools}
          className="font-mono text-[0.6rem] px-1.5 py-0.5 border border-orange/40 text-orange ml-auto hover:bg-orange/10"
          data-testid="chronicle-only-tools"
          title="Show only tool-call audit entries (the old SIGNED LOG view)"
        >only tools</button>
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin p-3 space-y-2">
        {showForm && (
          <NewEntryForm
            projectId={projectId}
            sessionId={selectedSession}
            onAdded={refresh}
            onClose={() => setShowForm(false)}
          />
        )}
        {loading && (
          <div className="font-mono text-[0.7rem] text-alloy text-center py-4">// loading…</div>
        )}
        {!loading && filtered.length === 0 && entries.length > 0 && (
          <div className="font-mono text-[0.7rem] text-alloy text-center py-8">
            // {entries.length} entries hidden by filters. Click <span className="text-cyan">reset</span> above.
          </div>
        )}
        {!loading && entries.length === 0 && (
          <div className="font-mono text-[0.7rem] text-alloy text-center py-8">
            // no entries yet. Chat with J or click + to start the chronicle.
          </div>
        )}
        {filtered.map((e) => (
          <EntryCard
            key={e.entry_id || e.entry_hash}
            entry={e}
            projectId={projectId}
            onRefresh={refresh}
          />
        ))}
      </div>
    </div>
  );
}
