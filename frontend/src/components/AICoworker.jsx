import { useState, useRef, useEffect } from "react";
import { PaperPlaneTilt, Sparkle, ShieldCheck, Pulse } from "@phosphor-icons/react";
import { aiChat, aiRefine, aiGovernance, evaluateGauntlet } from "@/lib/api";

const TABS = [
  { key: "chat", label: "CHAT", model: "GEMINI 3.1", Icon: PaperPlaneTilt },
  { key: "refine", label: "REFINE", model: "GPT-5.2", Icon: Sparkle },
  { key: "gauntlet", label: "GAUNTLET", model: "CLAUDE 4.5", Icon: ShieldCheck },
  { key: "logs", label: "LOGS", model: "TRACE", Icon: Pulse },
];

function truncateTree(tree, depth = 0, lines = []) {
  if (lines.length > 40) return lines;
  for (const n of tree) {
    lines.push("  ".repeat(depth) + (n.type === "dir" ? "/" : "") + n.name);
    if (n.type === "dir" && n.children) truncateTree(n.children, depth + 1, lines);
  }
  return lines;
}

export default function AICoworker({ project, activeTab, tree, onScoreUpdate, onApplyRefined }) {
  const [tab, setTab] = useState("chat");

  return (
    <div className="flex flex-col h-full min-w-0" data-testid="ai-coworker">
      <div className="flex items-stretch border-b border-cyan/10 bg-midnight">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              data-testid={`ai-tab-${t.key}`}
              onClick={() => setTab(t.key)}
              className={`flex-1 flex flex-col items-center justify-center py-2 gap-0.5 ${
                active ? "text-cyan border-b border-cyan bg-steel" : "text-alloy hover:text-gridwhite"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <t.Icon size={11} weight={active ? "fill" : "regular"} />
                <span className="font-display text-[0.6rem] tracking-[0.2em]">{t.label}</span>
              </div>
              <span className="font-mono text-[0.55rem] text-alloy">{t.model}</span>
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-h-0">
        {tab === "chat" && <ChatTab project={project} activeTab={activeTab} tree={tree} />}
        {tab === "refine" && (
          <RefineTab
            activeTab={activeTab}
            onApplyRefined={onApplyRefined}
            onScoreUpdate={onScoreUpdate}
          />
        )}
        {tab === "gauntlet" && (
          <GauntletTab activeTab={activeTab} onScoreUpdate={onScoreUpdate} />
        )}
        {tab === "logs" && <LogsTab />}
      </div>
    </div>
  );
}

function ChatTab({ project, activeTab, tree }) {
  const [messages, setMessages] = useState([
    { role: "system", content: "J is online. Five Masters loaded. What needs building?" },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send() {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setBusy(true);
    try {
      const treeSummary = truncateTree(tree || []).join("\n");
      const payload = {
        conversation_id: conversationId,
        message: text,
        file_path: activeTab?.path,
        file_content: activeTab?.content?.slice(0, 8000),
        language: activeTab?.language,
        tree_summary: treeSummary,
      };
      const r = await aiChat(payload);
      setConversationId(r.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `// LLM error: ${e?.response?.data?.detail || e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-auto scrollbar-thin p-3 space-y-3" data-testid="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`text-sm ${m.role === "user" ? "text-gridwhite" : m.role === "system" ? "text-alloy" : "text-gridwhite"}`}>
            <div className="font-mono text-[0.6rem] tracking-widest text-cyan mb-0.5">
              {m.role === "user" ? "// YOU" : m.role === "system" ? "// J:SYSTEM" : "// J"}
            </div>
            <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
          </div>
        ))}
        {busy && <div className="font-mono text-[0.65rem] text-cyan">// J is thinking…</div>}
      </div>
      <div className="border-t border-cyan/10 p-2 flex gap-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          placeholder="Talk to J…"
          rows={2}
          className="flex-1 bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs text-gridwhite resize-none"
        />
        <button
          data-testid="chat-send"
          onClick={send}
          disabled={busy || !input.trim()}
          className="btn-solid"
        >
          <PaperPlaneTilt size={12} weight="fill" /> SEND
        </button>
      </div>
    </div>
  );
}

function RefineTab({ activeTab, onApplyRefined, onScoreUpdate }) {
  const [instruction, setInstruction] = useState("");
  const [refined, setRefined] = useState("");
  const [astReport, setAstReport] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!activeTab || !instruction.trim()) return;
    setBusy(true); setRefined(""); setAstReport(null);
    try {
      const r = await aiRefine({
        code: activeTab.content,
        instruction,
        language: activeTab.language,
      });
      setRefined(r.refined);
      setAstReport(r.ast_report);
      onScoreUpdate(r.ast_report, r.ast_report.issues.length);
    } catch (e) {
      setRefined(`// ERROR: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full p-3 gap-2" data-testid="refine-panel">
      <div className="font-mono text-[0.65rem] text-alloy">// INLINE REFINEMENT · GPT-5.2</div>
      <textarea
        data-testid="refine-instruction"
        placeholder="e.g. 'replace range(len(...)) with enumerate, add type hints'"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        rows={3}
        className="bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs text-gridwhite resize-none"
      />
      <button data-testid="refine-run" onClick={run} disabled={busy || !activeTab} className="btn-solid w-full justify-center">
        {busy ? "REFINING…" : "RUN REFINE"}
      </button>
      {refined && (
        <>
          <div className="font-mono text-[0.65rem] text-cyan mt-2">// PROPOSED OUTPUT</div>
          <pre className="flex-1 overflow-auto scrollbar-thin bg-steel border border-cyan/15 p-2 font-mono text-[0.7rem] text-gridwhite whitespace-pre-wrap">{refined}</pre>
          {astReport && <MastersBadge report={astReport} />}
          <div className="flex gap-2">
            <button
              data-testid="refine-apply"
              onClick={() => onApplyRefined(refined)}
              className="btn-solid flex-1 justify-center"
            >APPLY</button>
            <button onClick={() => setRefined("")} className="btn-ghost flex-1 justify-center">DISCARD</button>
          </div>
        </>
      )}
    </div>
  );
}

function GauntletTab({ activeTab, onScoreUpdate }) {
  const [astReport, setAstReport] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [busy, setBusy] = useState(false);

  async function quickAST() {
    if (!activeTab) return;
    setBusy(true);
    try {
      const r = await evaluateGauntlet(activeTab.content, activeTab.language);
      setAstReport(r);
      setVerdict(null);
      onScoreUpdate(r, r.issues.length);
    } finally { setBusy(false); }
  }

  async function fullGauntlet() {
    if (!activeTab) return;
    setBusy(true);
    try {
      const r = await aiGovernance({ code: activeTab.content, language: activeTab.language });
      setAstReport(r.ast_report);
      setVerdict(r.llm_verdict);
      onScoreUpdate(r.ast_report, r.ast_report.issues.length);
    } catch (e) {
      setVerdict({ verdict: "FAIL", summary: e?.response?.data?.detail || e.message, masters: [], fixes: [] });
    } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-col h-full p-3 gap-2 overflow-auto scrollbar-thin" data-testid="gauntlet-panel">
      <div className="font-mono text-[0.65rem] text-alloy">// FIVE MASTERS GAUNTLET · CLAUDE SONNET 4.5</div>
      <div className="flex gap-2">
        <button data-testid="gauntlet-ast" onClick={quickAST} disabled={busy || !activeTab} className="btn-ghost flex-1 justify-center">
          QUICK AST
        </button>
        <button data-testid="gauntlet-full" onClick={fullGauntlet} disabled={busy || !activeTab} className="btn-solid flex-1 justify-center">
          {busy ? "EVAL…" : "FULL GAUNTLET"}
        </button>
      </div>

      {astReport && <MastersBadge report={astReport} />}

      {verdict && (
        <div className="mt-2 panel p-3" data-testid="gauntlet-verdict">
          <div className="flex items-center justify-between mb-2">
            <div className="font-display text-[0.7rem] tracking-[0.25em] text-cyan">J VERDICT</div>
            <div
              className="font-display text-[0.7rem] tracking-[0.3em] px-2 py-0.5"
              style={{
                color: verdict.verdict === "PASS" ? "var(--viridian)" : "var(--orange)",
                border: `1px solid ${verdict.verdict === "PASS" ? "var(--viridian)" : "var(--orange)"}`,
              }}
            >{verdict.verdict}</div>
          </div>
          <div className="font-mono text-[0.7rem] text-gridwhite/90 whitespace-pre-wrap">{verdict.summary}</div>
          {verdict.fixes?.length > 0 && (
            <div className="mt-2 space-y-1">
              <div className="font-mono text-[0.6rem] text-alloy">// FIXES</div>
              {verdict.fixes.map((f, i) => (
                <div key={i} className="font-mono text-[0.65rem] text-orange">▸ {f}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {astReport?.issues?.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="font-mono text-[0.6rem] text-alloy">// AST ISSUES ({astReport.issues.length})</div>
          {astReport.issues.slice(0, 20).map((iss, i) => (
            <div key={i} className="font-mono text-[0.7rem] flex gap-2">
              <span className="text-cyan">L{iss.line}</span>
              <span style={{ color: iss.severity === "error" ? "var(--orange)" : "var(--alloy-gray)" }}>[{iss.master}]</span>
              <span className="text-gridwhite/80 flex-1">{iss.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MastersBadge({ report }) {
  return (
    <div className="grid grid-cols-5 gap-1" data-testid="masters-badge">
      {report.masters.map((m) => (
        <div
          key={m.key}
          className="panel p-1.5 text-center"
          style={{ borderColor: m.passed ? "rgba(31,143,107,0.4)" : "rgba(255,106,26,0.5)" }}
        >
          <div
            className="font-display text-[0.55rem] tracking-[0.1em]"
            style={{ color: m.passed ? "var(--viridian)" : "var(--orange)" }}
          >
            {m.passed ? "OK" : "FAIL"}
          </div>
          <div className="font-mono text-[0.6rem] text-gridwhite/90 truncate">{m.key.slice(0, 8)}</div>
        </div>
      ))}
    </div>
  );
}

function LogsTab() {
  return (
    <div className="p-3 font-mono text-[0.7rem] text-alloy h-full overflow-auto scrollbar-thin" data-testid="logs-panel">
      <div>// SUBSTRATE TRACE</div>
      <div className="mt-2 space-y-0.5">
        <div><span className="text-cyan">[boot]</span> J persona loaded</div>
        <div><span className="text-cyan">[boot]</span> Five Masters AST engine: <span className="text-viridian">OK</span></div>
        <div><span className="text-cyan">[boot]</span> Destructive interlock: <span className="text-viridian">ARMED</span></div>
        <div><span className="text-cyan">[boot]</span> LLM rotation: gemini-3.1 / gpt-5.2 / claude-sonnet-4.5</div>
        <div><span className="text-cyan">[boot]</span> Override password: required for destructive ops</div>
        <div className="text-alloy/60">// trace ready</div>
      </div>
    </div>
  );
}
