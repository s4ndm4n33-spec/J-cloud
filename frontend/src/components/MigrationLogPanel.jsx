import { useEffect, useState } from "react";
import { Scroll, ArrowsClockwise, Plus, X, CircleNotch } from "@phosphor-icons/react";
import { getMigrationLog, addMigrationEntry } from "@/lib/api";

export default function MigrationLogPanel({ project, onAICall }) {
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ title: "", problem: "", fix: "", why: "", next_step: "" });

  async function refresh() {
    if (!project) return;
    setBusy(true);
    try {
      const r = await getMigrationLog(project.project_id);
      setContent(r.content || "// (empty — the log will populate as J works)");
    } catch (e) {
      setContent(`// failed to load log: ${e?.response?.data?.detail || e.message}`);
    } finally { setBusy(false); }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [project?.project_id]);

  async function save() {
    if (!draft.title.trim() || !project) return;
    setBusy(true);
    try {
      await addMigrationEntry(project.project_id, draft);
      setDraft({ title: "", problem: "", fix: "", why: "", next_step: "" });
      setAdding(false);
      await refresh();
      onAICall?.();
    } catch (e) {
      console.error("add entry failed", e);
    } finally { setBusy(false); }
  }

  if (!project) {
    return <div className="p-3 font-mono text-xs text-alloy">// open a project</div>;
  }

  return (
    <div className="flex flex-col h-full" data-testid="migration-log-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10">
        <div className="flex items-center gap-1.5">
          <Scroll size={13} className="text-cyan" weight="fill" />
          <div className="font-display text-cyan tracking-widest text-[0.65rem]">MIGRATION LOG</div>
          <div className="font-mono text-[0.6rem] text-alloy">// .gauntlet/migration.log.md</div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            data-testid="log-add-toggle"
            onClick={() => setAdding((v) => !v)}
            title={adding ? "Cancel" : "Add manual entry"}
            className="text-alloy hover:text-cyan"
          >{adding ? <X size={12} weight="bold" /> : <Plus size={12} weight="bold" />}</button>
          <button
            data-testid="log-refresh"
            onClick={refresh}
            disabled={busy}
            className="text-alloy hover:text-cyan"
          >
            {busy ? <CircleNotch size={12} className="animate-spin" /> : <ArrowsClockwise size={12} />}
          </button>
        </div>
      </div>

      {adding && (
        <div className="border-b border-cyan/10 p-2 space-y-1.5 bg-steel/40" data-testid="log-add-form">
          <input
            autoFocus
            data-testid="log-title"
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            placeholder="title (e.g. 'Hardened CORS for prod')"
            className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs"
          />
          <textarea
            data-testid="log-problem"
            value={draft.problem}
            onChange={(e) => setDraft({ ...draft, problem: e.target.value })}
            placeholder="problem"
            rows={2}
            className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] resize-none"
          />
          <textarea
            data-testid="log-fix"
            value={draft.fix}
            onChange={(e) => setDraft({ ...draft, fix: e.target.value })}
            placeholder="fix"
            rows={2}
            className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] resize-none"
          />
          <textarea
            data-testid="log-why"
            value={draft.why}
            onChange={(e) => setDraft({ ...draft, why: e.target.value })}
            placeholder="why"
            rows={2}
            className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] resize-none"
          />
          <textarea
            data-testid="log-next"
            value={draft.next_step}
            onChange={(e) => setDraft({ ...draft, next_step: e.target.value })}
            placeholder="next step"
            rows={2}
            className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] resize-none"
          />
          <button
            data-testid="log-save"
            onClick={save}
            disabled={busy || !draft.title.trim()}
            className="btn-solid w-full justify-center text-[0.7rem]"
          >
            {busy ? "SIGNING…" : "SIGN + APPEND"}
          </button>
        </div>
      )}

      <div className="flex-1 overflow-auto scrollbar-thin p-3" data-testid="log-content">
        <pre className="font-mono text-[0.7rem] text-gridwhite/90 whitespace-pre-wrap leading-relaxed">{content}</pre>
      </div>
    </div>
  );
}
