import { useState, useRef, useEffect } from "react";
import { PaperPlaneTilt, Sparkle, ShieldCheck, Pulse, Gauge, Wrench, CaretDown, CaretRight, Book } from "@phosphor-icons/react";
import { aiChat, aiAgent, aiRefine, aiGovernance, evaluateGauntlet } from "@/lib/api";
import AuditPanel from "@/components/AuditPanel";
import ChroniclePanel from "@/components/ChroniclePanel";

const TABS = [
  { key: "chat", label: "CHAT", model: "GEMINI 3", Icon: PaperPlaneTilt },
  { key: "refine", label: "REFINE", model: "GPT-5.2", Icon: Sparkle },
  { key: "gauntlet", label: "GAUNTLET", model: "CLAUDE 4.5", Icon: ShieldCheck },
  { key: "audit", label: "AUDIT", model: "/100", Icon: Gauge },
  { key: "chronicle", label: "CHRONICLE", model: "BLACKBOX", Icon: Book },
  { key: "logs", label: "TRACE", model: "BOOT", Icon: Pulse },
];

function truncateTree(tree, depth = 0, lines = []) {
  if (lines.length > 40) return lines;
  for (const n of tree) {
    lines.push("  ".repeat(depth) + (n.type === "dir" ? "/" : "") + n.name);
    if (n.type === "dir" && n.children) truncateTree(n.children, depth + 1, lines);
  }
  return lines;
}

export default function AICoworker({ project, activeTab, tree, onScoreUpdate, onApplyRefined, onAICall }) {
  const [tab, setTab] = useState("chat");

  // Chat state lifted from ChatTab so tab switches don't wipe the conversation.
  // Only `END SESSION` (in ChatTab) clears it.
  const [chatMessages, setChatMessages] = useState([
    { role: "system", content: "J is online. Five Masters loaded. What needs building?" },
  ]);
  const [chatConversationId, setChatConversationId] = useState(null);
  const [chatAgentMode, setChatAgentMode] = useState(true);

  return (
    <div className="flex flex-col h-full min-w-0" data-testid="ai-coworker">
      <div className="flex items-stretch border-b border-cyan/10 bg-midnight overflow-x-auto scrollbar-thin">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              data-testid={`ai-tab-${t.key}`}
              onClick={() => setTab(t.key)}
              className={`flex-1 min-w-[5rem] flex flex-col items-center justify-center py-2 gap-0.5 ${
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
        {/* Chat tab is always rendered but hidden when not active — keeps the
            DOM (scroll position, textarea focus) AND state alive across tab switches. */}
        <div className={tab === "chat" ? "h-full" : "hidden"}>
          <ChatTab
            project={project}
            activeTab={activeTab}
            tree={tree}
            onAICall={onAICall}
            messages={chatMessages}
            setMessages={setChatMessages}
            conversationId={chatConversationId}
            setConversationId={setChatConversationId}
            agentMode={chatAgentMode}
            setAgentMode={setChatAgentMode}
          />
        </div>
        {tab === "refine" && (
          <RefineTab
            activeTab={activeTab}
            onApplyRefined={onApplyRefined}
            onScoreUpdate={onScoreUpdate}
            onAICall={onAICall}
          />
        )}
        {tab === "gauntlet" && (
          <GauntletTab activeTab={activeTab} onScoreUpdate={onScoreUpdate} onAICall={onAICall} />
        )}
        {tab === "audit" && <AuditPanel project={project} onAICall={onAICall} />}
        {tab === "chronicle" && <ChroniclePanel project={project} />}
        {tab === "logs" && <LogsTab />}
      </div>
    </div>
  );
}

function ChatTab({
  project, activeTab, tree, onAICall,
  messages, setMessages,
  conversationId, setConversationId,
  agentMode, setAgentMode,
}) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ending, setEnding] = useState(false);
  const scrollRef = useRef(null);
  // AUTO mode = bump max_steps to 100. Sticky per browser (localStorage).
  const [autoMode, setAutoMode] = useState(() => {
    try { return localStorage.getItem("gauntlet_auto_mode") === "1"; }
    catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem("gauntlet_auto_mode", autoMode ? "1" : "0"); } catch { /* ignore */ }
  }, [autoMode]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const hasUserActivity = messages.some((m) => m.role === "user");

  async function endSession() {
    if (ending || !hasUserActivity) return;
    if (!project) {
      setMessages((prev) => [...prev, { role: "assistant", content: "// open a project first" }]);
      return;
    }
    if (!conversationId) {
      // No conversation has been opened yet (no messages sent) — just clear.
      setMessages([{ role: "system", content: "J is online. Five Masters loaded. What needs building?" }]);
      return;
    }
    setEnding(true);
    try {
      const { closeChatSession } = await import("@/lib/api");
      const r = await closeChatSession(project.project_id, conversationId);
      setMessages((prev) => [
        ...prev,
        { role: "system", content: `// SESSION CLOSED · chronicle entry written${r.email_sent ? " · transcript emailed" : ""}.` },
        r.narrative ? { role: "assistant", content: r.narrative, meta: { source: "chronicle" } } : null,
        { role: "system", content: "// new session starts on your next message." },
      ].filter(Boolean));
      setConversationId(null);
      onAICall?.();
    } catch (e) {
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: `// failed to close session: ${e?.response?.data?.detail || e.message}`,
      }]);
    } finally { setEnding(false); }
  }

  async function send() {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setBusy(true);
    try {
      if (agentMode) {
        if (!project) {
          setMessages((prev) => [...prev, { role: "assistant", content: "// open a project first" }]);
          return;
        }
        const r = await aiAgent({
          project_id: project.project_id,
          conversation_id: conversationId,
          message: text,
          auto_mode: autoMode,
        });
        setConversationId(r.conversation_id);
        setMessages((prev) => [...prev, { role: "agent", steps: r.steps, final: r.final, done_reason: r.done_reason }]);
        onAICall?.();
      } else {
        const treeSummary = truncateTree(tree || []).join("\n");
        const r = await aiChat({
          conversation_id: conversationId,
          message: text,
          file_path: activeTab?.path,
          file_content: activeTab?.content?.slice(0, 8000),
          language: activeTab?.language,
          tree_summary: treeSummary,
        });
        setConversationId(r.conversation_id);
        setMessages((prev) => [...prev, { role: "assistant", content: r.reply, meta: r.meta }]);
        onAICall?.();
      }
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
          <ChatMessage key={i} msg={m} />
        ))}
        {busy && <div className="font-mono text-[0.65rem] text-cyan">// J is {agentMode ? "working" : "thinking"}…</div>}
      </div>

      <div className="px-2 pt-1 flex items-center gap-2 border-t border-cyan/10">
        <label className="flex items-center gap-1.5 font-mono text-[0.65rem] cursor-pointer select-none" data-testid="agent-mode-toggle">
          <input type="checkbox" checked={agentMode} onChange={(e) => setAgentMode(e.target.checked)} className="accent-cyan-500" />
          <Wrench size={11} className={agentMode ? "text-cyan" : "text-alloy"} weight={agentMode ? "fill" : "regular"} />
          <span className={agentMode ? "text-cyan" : "text-alloy"}>
            AGENT MODE {agentMode ? "ON" : "OFF"}
          </span>
          <span className="text-alloy ml-1">
            {agentMode ? "// J can mutate files" : "// chat only"}
          </span>
        </label>
        {agentMode && (
          <button
            data-testid="auto-mode-toggle"
            onClick={() => setAutoMode((v) => !v)}
            title={autoMode
              ? "AUTO ON — J runs up to 100 tool calls per message without pausing. Click to disable."
              : "AUTO OFF — J stops after ~40 tool calls per message. Click to enable AUTO."}
            className={`flex items-center gap-1 px-2 py-0.5 font-mono text-[0.65rem] tracking-wider transition-colors ${
              autoMode
                ? "text-midnight bg-cyan hover:bg-cyan/80"
                : "text-alloy border border-alloy/40 hover:text-cyan hover:border-cyan"
            }`}
          >
            {autoMode ? "// AUTO · ON" : "// AUTO · OFF"}
          </button>
        )}
        <button
          data-testid="end-session-button"
          onClick={endSession}
          disabled={ending || busy || !hasUserActivity}
          title={hasUserActivity
            ? "Close this conversation — J writes a chronicle narrative + (if opted in) emails you the transcript."
            : "Send at least one message before closing a session."}
          className="ml-auto font-mono text-[0.65rem] px-2 py-0.5 border border-orange/40 text-orange hover:bg-orange/10 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {ending ? "CLOSING…" : "END SESSION"}
        </button>
      </div>
      <div className="p-2 flex gap-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          placeholder={agentMode ? "Tell J what to build…" : "Talk to J…"}
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

function ChatMessage({ msg }) {
  if (msg.role === "user") {
    return (
      <div className="text-sm text-gridwhite">
        <div className="font-mono text-[0.6rem] tracking-widest text-cyan mb-0.5">// YOU</div>
        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
      </div>
    );
  }
  if (msg.role === "system") {
    return (
      <div className="text-sm text-alloy">
        <div className="font-mono text-[0.6rem] tracking-widest text-cyan mb-0.5">// J:SYSTEM</div>
        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
      </div>
    );
  }
  if (msg.role === "agent") {
    return (
      <div className="text-sm text-gridwhite" data-testid="agent-message">
        <div className="font-mono text-[0.6rem] tracking-widest text-cyan mb-0.5 flex gap-2">
          <span>// J · AGENT</span>
          <span className="text-alloy">· {(msg.steps || []).filter(s => s.type==="tool").length} tool call{(msg.steps||[]).filter(s=>s.type==="tool").length===1?"":"s"}</span>
          {msg.done_reason && <span className="text-alloy">· {msg.done_reason}</span>}
        </div>
        <div className="space-y-1.5">
          {(msg.steps || []).map((s, i) => (
            s.type === "assistant"
              ? (s.text ? <div key={i} className="whitespace-pre-wrap leading-relaxed text-gridwhite/95">{s.text}</div> : null)
              : <ToolCard key={i} step={s} />
          ))}
          {msg.final && <div className="mt-2 whitespace-pre-wrap text-gridwhite font-medium">{msg.final}</div>}
        </div>
      </div>
    );
  }
  // legacy assistant (non-agent)
  return (
    <div className="text-sm text-gridwhite">
      <div className="font-mono text-[0.6rem] tracking-widest text-cyan mb-0.5 flex items-center gap-2">
        <span>// J</span>
        {msg.meta?.step_used && (
          <span className="text-alloy" data-testid="chat-served-by">
            · via {msg.meta.step_used.source}/{msg.meta.step_used.provider}
          </span>
        )}
      </div>
      <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
    </div>
  );
}

function ToolCard({ step }) {
  const [open, setOpen] = useState(false);
  const isErr = !!step.result?.error;
  const isBlocked = (step.result?.error || "").includes("BLOCKED");
  const color = isBlocked ? "var(--orange)" : isErr ? "#FF6A1A" : "var(--viridian)";
  const argsPreview = Object.entries(step.args || {})
    .map(([k, v]) => `${k}=${typeof v === "string" ? `"${v.slice(0, 30)}${v.length > 30 ? "…" : ""}"` : JSON.stringify(v).slice(0, 30)}`)
    .join(" ");
  return (
    <div className="border border-cyan/15 panel" data-testid={`tool-card-${step.name}`}>
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center gap-2 px-2 py-1 text-left">
        {open ? <CaretDown size={10} /> : <CaretRight size={10} />}
        <Wrench size={11} style={{ color }} weight="fill" />
        <span className="font-mono text-[0.7rem] text-cyan">{step.name}</span>
        <span className="font-mono text-[0.6rem] text-alloy truncate flex-1">{argsPreview}</span>
        <span className="font-mono text-[0.6rem]" style={{ color }}>{isBlocked ? "BLOCKED" : isErr ? "ERROR" : "OK"}</span>
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1">
          <details>
            <summary className="font-mono text-[0.6rem] text-alloy cursor-pointer">args</summary>
            <pre className="font-mono text-[0.65rem] text-gridwhite/90 bg-steel p-1.5 overflow-auto max-h-32">{JSON.stringify(step.args || {}, null, 2)}</pre>
          </details>
          <details open>
            <summary className="font-mono text-[0.6rem] text-alloy cursor-pointer">result</summary>
            <pre className="font-mono text-[0.65rem] text-gridwhite/90 bg-steel p-1.5 overflow-auto max-h-48">{JSON.stringify(step.result || {}, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

function RefineTab({ activeTab, onApplyRefined, onScoreUpdate, onAICall }) {
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
      onAICall?.();
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

function GauntletTab({ activeTab, onScoreUpdate, onAICall }) {
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
      onAICall?.();
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
