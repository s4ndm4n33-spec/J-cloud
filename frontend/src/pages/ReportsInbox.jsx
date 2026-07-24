/* Owner-only user report inbox. Sits above the abuse-flag dashboard on
   /admin. Renders each report with expandable context (recent chat turns +
   telemetry, for bug/error kinds). */
import { useEffect, useState } from "react";
import { ChatCircle, CheckCircle, EnvelopeOpen, Warning, Bug, Question, Lightbulb } from "@phosphor-icons/react";
import { adminListReports, adminMarkReportRead, adminMarkReportResolved } from "@/lib/api";

const KIND_META = {
  bug:        { Icon: Bug,      color: "text-rose-400",   label: "BUG" },
  error:      { Icon: Warning,  color: "text-orange",     label: "ERROR" },
  question:   { Icon: Question, color: "text-cyan",       label: "QUESTION" },
  feedback:   { Icon: ChatCircle, color: "text-alloy",    label: "FEEDBACK" },
  suggestion: { Icon: Lightbulb, color: "text-yellow-300", label: "SUGGESTION" },
};

const STATUS_STYLE = {
  new:      "text-orange border-orange/40",
  read:     "text-cyan border-cyan/40",
  resolved: "text-alloy border-alloy/40",
};

function fmtTs(iso) {
  if (!iso) return "";
  try { return new Date(iso).toISOString().replace("T", " ").slice(0, 19) + "Z"; }
  catch { return iso; }
}

export default function ReportsInbox() {
  const [reports, setReports] = useState([]);
  const [unread, setUnread] = useState(0);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");   // "" | new | read | resolved
  const [kindFilter, setKindFilter] = useState("");        // "" | bug | error | ...
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [expandedId, setExpandedId] = useState(null);

  async function load() {
    setLoading(true); setErr("");
    try {
      const d = await adminListReports({
        status: statusFilter || undefined,
        kind: kindFilter || undefined,
        limit: 100,
      });
      setReports(d.reports || []);
      setUnread(d.unread || 0);
      setTotal(d.total || 0);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "load failed");
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [statusFilter, kindFilter]);  // eslint-disable-line

  async function markRead(id) {
    try { await adminMarkReportRead(id); await load(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  async function markResolved(id) {
    const note = window.prompt("resolution note (optional):", "") ?? "";
    try { await adminMarkReportResolved(id, note); await load(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }

  return (
    <section className="mb-8" data-testid="admin-reports-inbox">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm tracking-widest text-cyan">
          // USER REPORTS <span className="text-alloy">· {total} total · </span>
          <span className={unread > 0 ? "text-orange" : "text-alloy"}>
            {unread} unread
          </span>
        </h2>
        <div className="flex gap-2 text-[0.7rem]">
          <select value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  data-testid="reports-filter-status"
                  className="bg-void border border-cyan/30 text-cyan px-2 py-1">
            <option value="">all statuses</option>
            <option value="new">new</option>
            <option value="read">read</option>
            <option value="resolved">resolved</option>
          </select>
          <select value={kindFilter}
                  onChange={(e) => setKindFilter(e.target.value)}
                  data-testid="reports-filter-kind"
                  className="bg-void border border-cyan/30 text-cyan px-2 py-1">
            <option value="">all kinds</option>
            {Object.keys(KIND_META).map(k => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>
      </div>

      {err && (
        <div className="panel border border-orange/40 bg-orange/5 p-3 text-orange text-sm mb-3"
             data-testid="reports-error">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-alloy text-[0.75rem]">// loading…</div>
      ) : reports.length === 0 ? (
        <div className="panel border border-cyan/10 p-4 text-alloy text-[0.75rem]"
             data-testid="reports-empty">
          {statusFilter || kindFilter
            ? "no reports match the current filter."
            : "no reports yet. inbox zero."}
        </div>
      ) : (
        <div className="divide-y divide-cyan/10 border border-cyan/10"
             data-testid="reports-list">
          {reports.map((r) => {
            const kmeta = KIND_META[r.kind] || KIND_META.feedback;
            const isOpen = expandedId === r.id;
            return (
              <div key={r.id}
                   className="p-3 hover:bg-cyan/[0.02]"
                   data-testid={`report-row-${r.id}`}>
                <div className="flex items-start gap-3">
                  <kmeta.Icon size={16} className={kmeta.color + " mt-0.5"} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-[0.65rem] ${kmeta.color}`}>{kmeta.label}</span>
                      <span className={`text-[0.65rem] px-1.5 py-[1px] border ${STATUS_STYLE[r.status] || ""}`}>
                        {r.status.toUpperCase()}
                      </span>
                      <span className="text-alloy text-[0.65rem]">{fmtTs(r.ts)}</span>
                      <span className="text-alloy text-[0.65rem] font-mono">· {r.user_id?.slice(0, 12)}</span>
                    </div>
                    <div className="text-gridwhite text-sm mt-1 truncate">{r.title}</div>
                    <div className="text-alloy text-[0.75rem] mt-1 whitespace-pre-wrap">
                      {r.body}
                    </div>
                    {r.context && (
                      <button
                        onClick={() => setExpandedId(isOpen ? null : r.id)}
                        data-testid={`report-toggle-context-${r.id}`}
                        className="text-cyan text-[0.65rem] mt-2 hover:underline">
                        {isOpen ? "hide context ↑" : "show context ↓"}
                      </button>
                    )}
                    {isOpen && r.context && (
                      <div className="mt-2 p-2 bg-void border border-cyan/10 text-[0.7rem] text-alloy space-y-2"
                           data-testid={`report-context-${r.id}`}>
                        {r.context.recent_turns?.length > 0 && (
                          <div>
                            <div className="text-cyan mb-1">// recent chat turns</div>
                            {r.context.recent_turns.map((t, i) => (
                              <div key={i} className="pl-2 border-l border-cyan/20 mb-1">
                                <div className="text-cyan/70">[{t.role}] {fmtTs(t.ts)}</div>
                                <div className="whitespace-pre-wrap">{String(t.content || "").slice(0, 400)}</div>
                              </div>
                            ))}
                          </div>
                        )}
                        {r.context.last_llm_call && (
                          <div>
                            <div className="text-cyan mb-1">// last LLM call</div>
                            <pre className="text-[0.65rem] whitespace-pre-wrap">
{JSON.stringify(r.context.last_llm_call, null, 2)}
                            </pre>
                          </div>
                        )}
                        {r.context.error_payload && (
                          <div>
                            <div className="text-cyan mb-1">// error payload</div>
                            <pre className="text-[0.65rem] whitespace-pre-wrap">
{JSON.stringify(r.context.error_payload, null, 2)}
                            </pre>
                          </div>
                        )}
                        {r.context.last_message && (
                          <div>
                            <div className="text-cyan mb-1">// last message (user opted in)</div>
                            <div className="pl-2 border-l border-cyan/20">
                              <div className="text-cyan/70">[{r.context.last_message.role}] {fmtTs(r.context.last_message.ts)}</div>
                              <div className="whitespace-pre-wrap">{String(r.context.last_message.content || "").slice(0, 400)}</div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    {r.resolution_note && (
                      <div className="mt-2 text-alloy text-[0.65rem]">
                        // resolution: {r.resolution_note}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-1 shrink-0">
                    {r.status === "new" && (
                      <button
                        onClick={() => markRead(r.id)}
                        title="mark as read"
                        data-testid={`report-mark-read-${r.id}`}
                        className="p-1 text-cyan/70 hover:text-cyan">
                        <EnvelopeOpen size={13} />
                      </button>
                    )}
                    {r.status !== "resolved" && (
                      <button
                        onClick={() => markResolved(r.id)}
                        title="mark as resolved (adds a note)"
                        data-testid={`report-mark-resolved-${r.id}`}
                        className="p-1 text-emerald-400/70 hover:text-emerald-400">
                        <CheckCircle size={13} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
