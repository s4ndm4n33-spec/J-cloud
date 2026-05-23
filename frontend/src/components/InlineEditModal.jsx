import { useState } from "react";
import { X, Sparkle, ShieldCheck } from "@phosphor-icons/react";
import { aiRefine, aiGovernance } from "@/lib/api";

export default function InlineEditModal({ tab, onClose, onApply }) {
  const [instruction, setInstruction] = useState("");
  const [stage, setStage] = useState("prompt"); // prompt | review
  const [refined, setRefined] = useState("");
  const [astReport, setAstReport] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!instruction.trim()) return;
    setBusy(true);
    try {
      const r = await aiRefine({
        code: tab.content,
        instruction,
        language: tab.language,
      });
      setRefined(r.refined);
      setAstReport(r.ast_report);
      // chain governance verdict
      const v = await aiGovernance({ code: r.refined, language: tab.language });
      setVerdict(v.llm_verdict);
      setStage("review");
    } catch (e) {
      setRefined(`// ERROR: ${e?.response?.data?.detail || e.message}`);
      setStage("review");
    } finally { setBusy(false); }
  }

  const passed = verdict?.verdict === "PASS";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-midnight/70 backdrop-blur-sm" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-3xl panel tick-corner p-5 relative"
        data-testid="inline-edit-modal"
      >
        <button onClick={onClose} className="absolute top-3 right-3 text-alloy hover:text-orange" data-testid="inline-close">
          <X size={14} weight="bold" />
        </button>

        <div className="flex items-center gap-2 mb-3">
          <Sparkle size={14} className="text-cyan" weight="fill" />
          <div className="font-display text-cyan tracking-[0.25em] text-xs">INLINE REFINE · CMD+K</div>
          <div className="ml-auto font-mono text-[0.65rem] text-alloy">{tab.path} · {tab.language}</div>
        </div>

        {stage === "prompt" && (
          <>
            <textarea
              autoFocus
              data-testid="inline-instruction"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); run(); }
              }}
              placeholder="Tell J what to do…  (cmd+enter to run)"
              rows={3}
              className="w-full bg-steel border border-cyan/30 px-3 py-2 font-mono text-sm text-gridwhite resize-none"
            />
            <div className="mt-3 flex items-center justify-between">
              <div className="font-mono text-[0.65rem] text-alloy">
                // Refine via GPT-5.2 → Gauntlet review via Claude Sonnet 4.5
              </div>
              <button data-testid="inline-run" onClick={run} disabled={busy || !instruction.trim()} className="btn-solid">
                {busy ? "WORKING…" : "RUN"}
              </button>
            </div>
          </>
        )}

        {stage === "review" && (
          <>
            <div className="flex items-center gap-2 mb-2">
              <ShieldCheck size={14} weight="fill" style={{ color: passed ? "var(--viridian)" : "var(--orange)" }} />
              <div
                className="font-display text-[0.7rem] tracking-[0.25em] px-2 py-0.5"
                style={{
                  color: passed ? "var(--viridian)" : "var(--orange)",
                  border: `1px solid ${passed ? "var(--viridian)" : "var(--orange)"}`,
                }}
                data-testid="inline-verdict-badge"
              >
                GAUNTLET: {verdict?.verdict || "?"}
              </div>
              <div className="font-mono text-[0.65rem] text-alloy ml-2">{verdict?.summary}</div>
            </div>

            {astReport && (
              <div className="grid grid-cols-5 gap-1 mb-2">
                {astReport.masters.map((m) => (
                  <div key={m.key} className="panel p-1 text-center"
                    style={{ borderColor: m.passed ? "rgba(31,143,107,0.4)" : "rgba(255,106,26,0.5)" }}>
                    <div className="font-display text-[0.55rem]" style={{ color: m.passed ? "var(--viridian)" : "var(--orange)" }}>{m.passed ? "OK" : "FAIL"}</div>
                    <div className="font-mono text-[0.6rem] text-gridwhite/85">{m.label}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="font-mono text-[0.65rem] text-alloy mb-1">// DIFF (proposed)</div>
            <pre className="max-h-72 overflow-auto scrollbar-thin bg-steel border border-cyan/15 p-2 font-mono text-[0.7rem] whitespace-pre-wrap text-gridwhite">{refined}</pre>

            {verdict?.fixes?.length > 0 && (
              <div className="mt-2 space-y-0.5">
                <div className="font-mono text-[0.6rem] text-alloy">// J SUGGESTS</div>
                {verdict.fixes.map((f, i) => (
                  <div key={i} className="font-mono text-[0.7rem] text-orange">▸ {f}</div>
                ))}
              </div>
            )}

            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setStage("prompt")} className="btn-ghost" data-testid="inline-back">
                BACK
              </button>
              <button onClick={onClose} className="btn-ghost" data-testid="inline-reject">REJECT</button>
              <button onClick={() => onApply(refined)} className="btn-solid" data-testid="inline-apply">
                APPLY
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
