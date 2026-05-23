import { useEffect, useState, useImperativeHandle, forwardRef, useCallback } from "react";
import axios from "axios";
import { Pulse, ArrowsClockwise } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

const TASK_GLYPH = { chat: "CHT", refine: "RFN", governance: "GNT" };

const ChainTelemetry = forwardRef(function ChainTelemetry(_props, ref) {
  const [events, setEvents] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/ai/telemetry?limit=5`, { withCredentials: true });
      setEvents(r.data.events || []);
    } catch {
      // Ignore - telemetry is informational
    }
  }, []);

  useImperativeHandle(ref, () => ({ refresh }), [refresh]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div
      className="h-7 border-t border-cyan/10 bg-midnight/90 flex items-center px-3 gap-3 overflow-x-auto scrollbar-thin"
      data-testid="chain-telemetry"
    >
      <div className="flex items-center gap-1.5 text-cyan font-display text-[0.6rem] tracking-[0.25em] shrink-0">
        <Pulse size={11} weight="fill" />
        TELEMETRY
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {events.length === 0 && (
          <span className="font-mono text-[0.65rem] text-alloy">// no llm calls yet</span>
        )}
        {events.map((e, i) => {
          const step = e.step_used;
          const isLatest = i === 0;
          const okColor = e.success ? "var(--viridian)" : "var(--orange)";
          return (
            <div
              key={`${e.ts}-${i}`}
              className={`flex items-center gap-1.5 font-mono text-[0.65rem] px-1.5 py-0.5 border ${isLatest ? "flash-cyan" : ""}`}
              style={{ borderColor: "rgba(0,217,255,0.15)" }}
              title={`${e.task} · ${e.ts}`}
              data-testid={`telemetry-${i}`}
            >
              <span
                className="w-1.5 h-1.5"
                style={{ background: okColor }}
              />
              <span className="text-cyan">{TASK_GLYPH[e.task] || "LLM"}</span>
              <span className="text-gridwhite">
                {step ? `${step.source[0].toUpperCase()}/${step.provider}` : "—"}
              </span>
              <span className="text-alloy">{e.total_ms}ms</span>
              {e.fallbacks > 0 && (
                <span className="text-orange">↻{e.fallbacks}</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="ml-auto flex items-center gap-3 shrink-0">
        <button
          onClick={refresh}
          className="text-alloy hover:text-cyan"
          title="Refresh"
          data-testid="telemetry-refresh"
        >
          <ArrowsClockwise size={11} />
        </button>
        <span className="font-mono text-[0.6rem] text-alloy tracking-widest">
          INTEGRITY: <span className="text-viridian">OK</span>
        </span>
      </div>
    </div>
  );
});

export default ChainTelemetry;
