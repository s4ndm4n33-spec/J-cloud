import { useState } from "react";
import { Gauge, Sparkle, Warning, CircleNotch } from "@phosphor-icons/react";
import { projectAudit, aiRefine, readFile, writeFile } from "@/lib/api";

const GRADE_COLORS = {
  S: "var(--viridian)",
  "A+": "var(--viridian)",
  A: "var(--viridian)",
  B: "#5DDE9D",
  C: "var(--cyan)",
  D: "var(--orange)",
  F: "var(--orange)",
};

export default function AuditPanel({ project, onAICall }) {
  const [audit, setAudit] = useState(null);
  const [busy, setBusy] = useState(false);
  const [optimizing, setOptimizing] = useState(null); // path being optimized
  const [proposal, setProposal] = useState(null); // {path, before, after, ast_report}

  async function run() {
    if (!project) return;
    setBusy(true);
    try {
      const r = await projectAudit(project.project_id);
      setAudit(r);
    } catch (e) {
      setAudit({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  }

  async function proposeFix(rec) {
    if (!rec.target_file || !project) return;
    setOptimizing(rec.target_file);
    try {
      const f = await readFile(project.project_id, rec.target_file);
      const r = await aiRefine({
        code: f.content,
        instruction: "Refactor this file to pass all Five Masters of the Gauntlet: efficiency (no range(len), no triple loops), error handling (no bare except), performance (no mutable defaults, no globals, shallow nesting), fault tolerance (guard I/O), clarity (snake_case, short focused functions, type hints, docstrings). Make MINIMAL targeted changes, preserve behavior.",
        language: f.language,
      });
      setProposal({ path: rec.target_file, before: f.content, after: r.refined, ast_report: r.ast_report });
      onAICall?.();
    } catch (e) {
      setProposal({ path: rec.target_file, error: e?.response?.data?.detail || e.message });
    } finally { setOptimizing(null); }
  }

  async function applyProposal() {
    if (!proposal?.after || !project) return;
    await writeFile(project.project_id, proposal.path, proposal.after);
    setProposal(null);
    await run(); // re-audit
  }

  if (!project) {
    return <div className="p-3 font-mono text-xs text-alloy">// no project</div>;
  }

  if (proposal) return <ProposalView proposal={proposal} onApply={applyProposal} onReject={() => setProposal(null)} />;

  if (!audit) {
    return (
      <div className="flex flex-col h-full p-4 gap-3 items-center justify-center text-center" data-testid="audit-empty">
        <Gauge size={32} className="text-cyan" weight="duotone" />
        <div className="font-display text-cyan tracking-[0.2em] text-sm">PROJECT AUDIT</div>
        <div className="font-mono text-[0.7rem] text-alloy max-w-xs leading-relaxed">
          Run a deterministic 100-point evaluation of <span className="text-cyan">{project.name}</span>.
          Five Masters, destructive scan, docs, tests, type-hints, hygiene, deps. J will NEVER refactor
          without your explicit go-ahead.
        </div>
        <button onClick={run} disabled={busy} className="btn-solid" data-testid="audit-run">
          {busy ? <CircleNotch size={12} className="animate-spin" /> : <Gauge size={12} weight="fill" />}
          {busy ? "AUDITING…" : "RUN AUDIT"}
        </button>
      </div>
    );
  }

  if (audit.error) {
    return <div className="p-3 font-mono text-[0.7rem] text-orange">// audit error: {audit.error}</div>;
  }

  const color = GRADE_COLORS[audit.grade] || "var(--cyan)";
  return (
    <div className="flex flex-col h-full overflow-auto scrollbar-thin" data-testid="audit-result">
      <div className="px-4 py-4 border-b border-cyan/10 flex items-center gap-4">
        <div className="text-center" style={{ minWidth: 80 }}>
          <div className="font-display text-5xl font-extrabold" style={{ color }} data-testid="audit-score">
            {Math.round(audit.score)}
          </div>
          <div className="font-mono text-[0.6rem] text-alloy tracking-[0.25em]">/ 100</div>
        </div>
        <div>
          <div className="font-display text-[0.65rem] tracking-[0.25em] text-alloy">GRADE</div>
          <div className="font-display text-3xl font-extrabold" style={{ color }} data-testid="audit-grade">{audit.grade}</div>
          <div className="font-mono text-[0.6rem] text-alloy mt-1">{audit.file_count} code files audited</div>
        </div>
        <button onClick={run} className="btn-ghost ml-auto text-[0.65rem]" data-testid="audit-rerun">
          RE-RUN
        </button>
      </div>

      <div className="px-4 py-3 space-y-1.5 border-b border-cyan/10">
        <div className="font-display text-[0.65rem] tracking-[0.25em] text-cyan mb-1">BREAKDOWN</div>
        {Object.entries(audit.breakdown).map(([k, v]) => (
          <Bar key={k} label={k.replace(/_/g, " ")} pts={v.pts} max={v.max} />
        ))}
      </div>

      {audit.recommendations.length > 0 && (
        <div className="px-4 py-3 space-y-2 border-b border-cyan/10">
          <div className="font-display text-[0.65rem] tracking-[0.25em] text-cyan">SUGGESTIONS · OPT-IN ONLY</div>
          <div className="font-mono text-[0.6rem] text-alloy">
            // J will propose changes for your review. Nothing is applied without your APPLY.
          </div>
          {audit.recommendations.map((r, i) => (
            <div key={i} className="border border-cyan/15 p-2 flex items-center gap-2" data-testid={`audit-rec-${i}`}>
              <div className="font-mono text-[0.65rem] text-viridian w-10 text-center">+{r.potential_gain}</div>
              <div className="flex-1 min-w-0">
                <div className="font-mono text-[0.7rem] text-gridwhite truncate">{r.title}</div>
                <div className="font-mono text-[0.55rem] text-alloy">[{r.category}]</div>
              </div>
              {r.target_file ? (
                <button
                  onClick={() => proposeFix(r)}
                  disabled={optimizing === r.target_file}
                  className="btn-solid text-[0.6rem] py-1 px-2"
                  data-testid={`audit-fix-${i}`}
                >
                  {optimizing === r.target_file ? <CircleNotch size={10} className="animate-spin" /> : <Sparkle size={10} />}
                  PROPOSE FIX
                </button>
              ) : (
                <span className="font-mono text-[0.55rem] text-alloy">manual</span>
              )}
            </div>
          ))}
        </div>
      )}

      {audit.destructive_findings.length > 0 && (
        <div className="px-4 py-3 space-y-1">
          <div className="font-display text-[0.65rem] tracking-[0.25em] text-orange flex items-center gap-1">
            <Warning size={12} weight="fill" /> DESTRUCTIVE FINDINGS
          </div>
          {audit.destructive_findings.slice(0, 10).map((d, i) => (
            <div key={i} className="font-mono text-[0.65rem] text-gridwhite/85">
              <span className="text-orange">{d.severity}</span>{" "}
              <span className="text-cyan">{d.file}:L{d.line}</span>{" "}
              <span className="text-alloy">{d.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Bar({ label, pts, max }) {
  const pct = Math.max(0, Math.min(1, pts / max));
  const color = pct > 0.85 ? "var(--viridian)" : pct > 0.5 ? "var(--cyan)" : "var(--orange)";
  return (
    <div className="font-mono text-[0.7rem]" data-testid={`audit-bar-${label.replace(/\s/g, "-")}`}>
      <div className="flex items-center justify-between">
        <span className="text-gridwhite/90 uppercase tracking-[0.1em]">{label}</span>
        <span className="text-alloy">{pts}/{max}</span>
      </div>
      <div className="h-1 bg-steel mt-0.5 overflow-hidden">
        <div className="h-full" style={{ width: `${pct * 100}%`, background: color }} />
      </div>
    </div>
  );
}

function ProposalView({ proposal, onApply, onReject }) {
  if (proposal.error) {
    return (
      <div className="p-3 font-mono text-[0.7rem] text-orange">
        // proposal failed: {proposal.error}
        <button onClick={onReject} className="btn-ghost mt-2 text-[0.65rem]">BACK</button>
      </div>
    );
  }
  const masters = proposal.ast_report?.masters || [];
  return (
    <div className="flex flex-col h-full overflow-auto scrollbar-thin p-3 gap-2" data-testid="audit-proposal">
      <div className="font-display text-[0.65rem] tracking-[0.25em] text-cyan">PROPOSAL · {proposal.path}</div>
      <div className="font-mono text-[0.65rem] text-alloy">
        // J prepared this refactor. Review and APPLY only if you approve.
      </div>
      <div className="grid grid-cols-5 gap-1">
        {masters.map((m) => (
          <div key={m.key} className="panel p-1 text-center"
            style={{ borderColor: m.passed ? "rgba(31,143,107,0.5)" : "rgba(255,106,26,0.5)" }}>
            <div className="font-display text-[0.55rem]" style={{ color: m.passed ? "var(--viridian)" : "var(--orange)" }}>{m.passed ? "OK" : "FAIL"}</div>
            <div className="font-mono text-[0.55rem] text-gridwhite/80">{m.label}</div>
          </div>
        ))}
      </div>
      <div className="font-mono text-[0.65rem] text-alloy">// PROPOSED</div>
      <pre className="flex-1 overflow-auto scrollbar-thin bg-steel border border-cyan/15 p-2 font-mono text-[0.7rem] text-gridwhite whitespace-pre-wrap">{proposal.after}</pre>
      <div className="flex gap-2">
        <button onClick={onReject} className="btn-ghost flex-1 justify-center" data-testid="proposal-reject">REJECT</button>
        <button onClick={onApply} className="btn-solid flex-1 justify-center" data-testid="proposal-apply">APPLY</button>
      </div>
    </div>
  );
}
