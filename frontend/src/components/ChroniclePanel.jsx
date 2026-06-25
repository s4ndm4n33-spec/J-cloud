import { useEffect, useState } from "react";
import { Scroll, Download, ShieldCheck, Plus, ArrowsClockwise, X, Robot, User, CircleNotch } from "@phosphor-icons/react";
import {
  listChronicle, listChronicleSessions, addChronicleEntry,
  verifyChronicle, exportChronicle,
} from "@/lib/api";

const SIGNER_COLORS = {
  J:      { fg: "var(--cyan)",     bg: "rgba(0,217,255,0.10)" },
  USER:   { fg: "var(--gridwhite)",bg: "rgba(231,236,245,0.06)" },
  SYSTEM: { fg: "var(--alloy)",    bg: "rgba(125,133,151,0.08)" },
};

function shortHash(h) { return (h || "").slice(0, 10); }

function EntryCard({ entry }) {
  const c = SIGNER_COLORS[entry.signer] || SIGNER_COLORS.SYSTEM;
  const Icon = entry.signer === "J" ? Robot : entry.signer === "USER" ? User : Scroll;
  return (
    <div
      className="border-l-2 px-3 py-2"
      style={{ borderColor: c.fg, background: c.bg }}
      data-testid={`chronicle-entry-${entry.entry_id}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon size={11} style={{ color: c.fg }} weight="fill" />
        <span className="font-mono text-[0.65rem]" style={{ color: c.fg }}>{entry.signer}</span>
        <span className="font-mono text-[0.6rem] text-alloy/70">{entry.kind}</span>
        <span className="font-mono text-[0.6rem] text-alloy ml-auto">{entry.ts_iso?.slice(0, 19).replace("T", " ")}</span>
        <span
          className="font-mono text-[0.55rem] text-alloy/50"
          title={`hash ${entry.entry_hash}\nprior ${entry.prior_hash}`}
        >{shortHash(entry.entry_hash)}</span>
      </div>
      <div className="font-display text-[0.8rem] text-gridwhite tracking-[0.05em] mb-1">{entry.title}</div>
      {entry.body && (
        <div className="font-mono text-[0.7rem] text-gridwhite/80 leading-relaxed whitespace-pre-wrap">
          {entry.body}
        </div>
      )}
      {(entry.tags || []).length > 0 && (
        <div className="flex gap-1 mt-2">
          {entry.tags.map((t, i) => (
            <span key={i} className="font-mono text-[0.55rem] text-cyan/80 border border-cyan/30 px-1.5 py-0.5">
              {t}
            </span>
          ))}
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
        {!loading && entries.length === 0 && (
          <div className="font-mono text-[0.7rem] text-alloy text-center py-8">
            // no entries yet. Chat with J or click + to start the chronicle.
          </div>
        )}
        {entries.map((e) => <EntryCard key={e.entry_id || e.entry_hash} entry={e} />)}
      </div>
    </div>
  );
}
