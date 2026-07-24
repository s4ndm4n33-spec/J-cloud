import { useState } from "react";
import { X, Bug, MessageCircleQuestion, Lightbulb, Send, Loader2 } from "lucide-react";
import { submitReport } from "@/lib/api";

const KINDS = [
  { id: "bug",        label: "BUG",        Icon: Bug,                  auto_context: true,
    hint: "Something broke. J will attach your last 6 chat turns + telemetry so I can debug." },
  { id: "error",      label: "ERROR",      Icon: Bug,                  auto_context: true,
    hint: "An error message you saw. Includes what J was trying to do." },
  { id: "question",   label: "QUESTION",   Icon: MessageCircleQuestion, auto_context: false,
    hint: "Ask me something. Nothing from your chat is attached unless you opt in." },
  { id: "feedback",   label: "FEEDBACK",   Icon: MessageCircleQuestion, auto_context: false,
    hint: "Praise, criticism, whatever. Nothing from your chat is attached unless you opt in." },
  { id: "suggestion", label: "SUGGESTION", Icon: Lightbulb,             auto_context: false,
    hint: "Idea for a feature. Nothing from your chat is attached unless you opt in." },
];

/**
 * Report modal. Rendered by AICoworker when the user clicks the "?" icon
 * in the header, or the inline "Report this" link on an error message.
 *
 * Privacy line: for `bug` and `error` reports, the backend auto-attaches
 * the last 6 chat turns + telemetry snapshot. For everything else, no chat
 * context leaves the client unless the user opts in via the checkbox.
 */
export default function ReportDialog({ open, onClose, initialKind = "bug", errorPayload = null }) {
  const [kind, setKind] = useState(initialKind);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [includeLast, setIncludeLast] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(null); // { report_id } after success
  const [err, setErr] = useState(null);

  if (!open) return null;

  const active = KINDS.find(k => k.id === kind) || KINDS[0];

  async function send() {
    if (!body.trim()) { setErr("say something first"); return; }
    setBusy(true); setErr(null);
    try {
      const r = await submitReport({
        kind, title, body,
        include_last_message: active.auto_context ? false : includeLast,
        error_payload: kind === "error" && errorPayload ? errorPayload : undefined,
      });
      setSent(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "send failed");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setKind(initialKind); setTitle(""); setBody("");
    setIncludeLast(false); setSent(null); setErr(null);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
         data-testid="report-dialog-overlay"
         onClick={onClose}>
      <div className="w-[520px] max-w-[92vw] rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-2xl"
           onClick={(e) => e.stopPropagation()}
           data-testid="report-dialog">
        <div className="flex items-center justify-between mb-4">
          <div className="text-cyan-300 text-sm font-mono">// report to J</div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200" data-testid="report-close">
            <X size={16} />
          </button>
        </div>

        {sent ? (
          <div className="text-sm text-slate-300 space-y-3">
            <div className="text-emerald-400 font-mono">// sent · {sent.report_id}</div>
            <div>J has been pinged. She&apos;ll see it in her ambient feed.</div>
            <div className="flex gap-2 pt-2">
              <button onClick={reset} className="px-3 py-1.5 text-xs rounded bg-slate-800 hover:bg-slate-700 border border-slate-700"
                      data-testid="report-send-another">
                send another
              </button>
              <button onClick={onClose} className="px-3 py-1.5 text-xs rounded bg-cyan-600 hover:bg-cyan-500 text-white"
                      data-testid="report-close-done">
                done
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-5 gap-1.5">
              {KINDS.map(k => (
                <button
                  key={k.id}
                  onClick={() => setKind(k.id)}
                  data-testid={`report-kind-${k.id}`}
                  className={`flex flex-col items-center gap-1 py-2 rounded border text-[10px] font-mono transition
                    ${kind === k.id
                      ? "border-cyan-500 bg-cyan-950/40 text-cyan-300"
                      : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"}`}>
                  <k.Icon size={14} />
                  {k.label}
                </button>
              ))}
            </div>

            <div className="text-[11px] text-slate-500 font-mono min-h-[16px]">
              {active.hint}
            </div>

            <input
              type="text"
              placeholder="title (optional, ≤120 chars)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={120}
              data-testid="report-title-input"
              className="w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 focus:border-cyan-500 outline-none text-sm text-slate-200 font-mono"
            />

            <textarea
              placeholder="what happened? / what would help? / what's on your mind?"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={4000}
              rows={6}
              data-testid="report-body-input"
              className="w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 focus:border-cyan-500 outline-none text-sm text-slate-200 font-mono resize-none"
            />

            {!active.auto_context && (
              <label className="flex items-center gap-2 text-[11px] text-slate-400 font-mono cursor-pointer"
                     data-testid="report-include-context-label">
                <input type="checkbox"
                       checked={includeLast}
                       onChange={(e) => setIncludeLast(e.target.checked)}
                       data-testid="report-include-context"
                       className="accent-cyan-500" />
                include my last chat message for context
              </label>
            )}
            {active.auto_context && (
              <div className="text-[11px] text-amber-300/80 font-mono">
                ⓘ recent chat turns + telemetry attached automatically for debugging
              </div>
            )}

            {err && (
              <div className="text-[11px] text-rose-400 font-mono" data-testid="report-error">
                // {err}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose}
                      disabled={busy}
                      className="px-3 py-1.5 text-xs rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300"
                      data-testid="report-cancel">
                cancel
              </button>
              <button onClick={send}
                      disabled={busy || !body.trim()}
                      data-testid="report-send"
                      className="px-3 py-1.5 text-xs rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-mono flex items-center gap-1.5">
                {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                send to J
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
