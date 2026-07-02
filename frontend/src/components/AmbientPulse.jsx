import { useEffect, useMemo, useState } from "react";
import {
  Pulse, X, ArrowRight, GitBranch, Warning, ShieldWarning, Broadcast, Trash,
} from "@phosphor-icons/react";
import {
  listAmbientEvents, markAmbientRead, clearAllAmbient, dismissAmbientEvent,
} from "@/lib/api";

const KIND_META = {
  GIT_DIVERGE:    { Icon: GitBranch,      color: "#00D9FF", label: "GIT" },
  CHRONICLE_FAIL: { Icon: Warning,        color: "#FF9F1A", label: "FAIL" },
  INTEGRITY_HALT: { Icon: ShieldWarning,  color: "#FF9F1A", label: "GATE" },
  CHAIN_EXHAUST:  { Icon: Broadcast,      color: "#FF3A3A", label: "LLM" },
};

const POLL_MS = 15000;

/**
 * The JARVIS heartbeat pulse — sits in the TopBar. Polls ambient events
 * every 15s; when unread ones exist, pulses cyan. Click to open the drawer.
 *
 * `onAskJ(event)` bubbles up to the IDE so the ambient message can be
 * injected as user context in the AI chat.
 */
export default function AmbientPulse({ onAskJ }) {
  const [events, setEvents] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  async function refresh() {
    try {
      const r = await listAmbientEvents({ limit: 20 });
      setEvents(r.events || []);
      setUnread(r.unread || 0);
    } catch { /* ignore transient errors */ }
  }

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, POLL_MS);
    return () => clearInterval(iv);
  }, []);

  async function openDrawer() {
    setOpen(true);
    if (unread > 0) {
      // Optimistically clear the badge; fire-and-forget mark-read
      const keys = events.filter((e) => !e.read).map((e) => e.event_key);
      setUnread(0);
      try { await markAmbientRead(keys); } catch { /* ignore */ }
      // Update local read flags
      setEvents((prev) => prev.map((e) => ({ ...e, read: true })));
    }
  }

  async function handleClearAll() {
    try {
      await clearAllAmbient();
      setEvents((prev) => prev.map((e) => ({ ...e, read: true })));
      setUnread(0);
    } catch { /* ignore */ }
  }

  async function handleDismiss(evt) {
    try {
      await dismissAmbientEvent(evt.event_key);
      setEvents((prev) => prev.filter((e) => e.event_key !== evt.event_key));
      if (!evt.read) setUnread((n) => Math.max(0, n - 1));
    } catch { /* ignore */ }
  }

  const pulsing = unread > 0;

  return (
    <>
      <button
        data-testid="ambient-pulse"
        onClick={openDrawer}
        title={pulsing ? `${unread} unread observation${unread === 1 ? "" : "s"}` : "Ambient awareness feed"}
        className={`relative flex items-center gap-1.5 px-2 py-1 font-mono text-[0.65rem] tracking-wider transition-colors ${
          pulsing
            ? "text-cyan border border-cyan/60"
            : "text-alloy hover:text-cyan border border-alloy/20 hover:border-cyan/30"
        }`}
      >
        <span className="relative flex items-center justify-center">
          <Pulse size={12} weight={pulsing ? "fill" : "regular"} />
          {pulsing && (
            <span className="absolute inline-flex h-full w-full rounded-full bg-cyan/40 opacity-75 animate-ping" />
          )}
        </span>
        <span>PULSE</span>
        {unread > 0 && (
          <span
            data-testid="ambient-pulse-badge"
            className="ml-0.5 px-1 min-w-[16px] text-center text-midnight bg-cyan"
          >{unread}</span>
        )}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-30 bg-midnight/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          <div
            data-testid="ambient-drawer"
            className="fixed right-0 top-0 bottom-0 w-[440px] z-40 bg-midnight border-l border-cyan/25 shadow-[-8px_0_24px_rgba(0,0,0,0.5)] flex flex-col"
          >
            <div className="flex items-center px-4 py-3 border-b border-cyan/20">
              <Pulse size={14} className="text-cyan" weight="fill" />
              <span className="ml-2 font-display tracking-[0.3em] text-[0.75rem] text-cyan">
                AMBIENT · THE LAB IS WATCHING
              </span>
              <button
                onClick={handleClearAll}
                disabled={events.every((e) => e.read)}
                title="Mark all as read"
                className="ml-auto text-alloy hover:text-cyan text-[0.6rem] font-mono tracking-wider px-2 py-1 disabled:opacity-30"
                data-testid="ambient-clear-all"
              >CLEAR ALL</button>
              <button
                onClick={() => setOpen(false)}
                data-testid="ambient-close"
                className="ml-1 text-alloy hover:text-orange"
              ><X size={14} weight="bold" /></button>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-thin">
              {events.length === 0 && (
                <div className="p-8 text-center font-mono text-[0.7rem] text-alloy/60 leading-relaxed">
                  // no observations yet.<br />
                  // the lab is quiet.
                </div>
              )}
              {events.map((evt) => {
                const meta = KIND_META[evt.kind] || {
                  Icon: Pulse, color: "#7D8597", label: evt.kind,
                };
                const Icon = meta.Icon;
                return (
                  <div
                    key={evt.event_key}
                    data-testid={`ambient-event-${evt.kind}`}
                    className={`p-3 border-b border-cyan/10 group ${evt.read ? "opacity-70" : ""}`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Icon size={12} style={{ color: meta.color }} weight="fill" />
                      <span className="font-mono text-[0.6rem] tracking-wider"
                            style={{ color: meta.color }}>{meta.label}</span>
                      <span className="font-mono text-[0.55rem] text-alloy/60 ml-auto">
                        {(evt.ts || "").slice(11, 19)}
                      </span>
                      <button
                        onClick={() => handleDismiss(evt)}
                        title="Dismiss"
                        className="text-alloy/50 hover:text-orange opacity-0 group-hover:opacity-100"
                        data-testid={`ambient-dismiss-${evt.event_key}`}
                      ><Trash size={10} /></button>
                    </div>
                    <div className="font-display text-[0.8rem] text-gridwhite mb-1">
                      {evt.title}
                    </div>
                    <div className="font-mono text-[0.7rem] text-gridwhite/70 leading-relaxed mb-2">
                      {evt.body}
                    </div>
                    {evt.action_hint && onAskJ && (
                      <button
                        onClick={() => { onAskJ(evt); setOpen(false); }}
                        data-testid={`ambient-ask-${evt.event_key}`}
                        className="flex items-center gap-1 font-mono text-[0.65rem] text-cyan hover:text-midnight hover:bg-cyan border border-cyan/40 hover:border-cyan px-2 py-1 transition-colors"
                      >
                        ASK J ABOUT THIS
                        <ArrowRight size={10} weight="bold" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="px-4 py-2 border-t border-cyan/10 font-mono text-[0.55rem] text-alloy/50 tracking-wider">
              // polling every {POLL_MS / 1000}s · {events.length} recent
            </div>
          </div>
        </>
      )}
    </>
  );
}
