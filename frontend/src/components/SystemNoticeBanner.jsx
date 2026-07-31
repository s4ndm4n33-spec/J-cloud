import { useEffect, useState, useCallback } from "react";
import { Warning, X } from "@phosphor-icons/react";
import { getSystemNotice } from "@/lib/api";

const DISMISSED_KEY = "gauntlet.system_notice.dismissed";

function severityStyles(sev) {
  switch (sev) {
    case "critical":
      return { border: "border-red-500", bg: "bg-red-950/70", text: "text-red-200", icon: "text-red-400" };
    case "info":
      return { border: "border-cyan/40", bg: "bg-cyan/10", text: "text-cyan", icon: "text-cyan" };
    case "warn":
    default:
      return { border: "border-amber/60", bg: "bg-amber/15", text: "text-amber", icon: "text-amber" };
  }
}

function relTimeUntil(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0 || Number.isNaN(ms)) return null;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `in ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `in ${m}m`;
  const h = Math.floor(m / 60);
  return `in ${h}h ${m % 60}m`;
}

/**
 * Top-of-screen banner for platform-wide announcements — most importantly,
 * warnings before redeploys that wipe unsaved workspaces. Polls every 60s.
 * Dismissible per-user (kept in localStorage keyed by notice_id).
 */
export default function SystemNoticeBanner() {
  const [notice, setNotice] = useState(null);
  const [dismissedIds, setDismissedIds] = useState(() => {
    try { return JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]"); }
    catch { return []; }
  });

  const load = useCallback(async () => {
    try {
      const r = await getSystemNotice();
      setNotice(r?.notice || null);
    } catch { /* silent — banner is best-effort */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  // Live countdown — retick every 15s while a notice with expires_at is shown
  const [_, setTick] = useState(0);
  useEffect(() => {
    if (!notice?.expires_at) return;
    const t = setInterval(() => setTick((n) => n + 1), 15_000);
    return () => clearInterval(t);
  }, [notice?.expires_at]);

  if (!notice) return null;
  if (dismissedIds.includes(notice.notice_id)) return null;

  const s = severityStyles(notice.severity);
  const rel = relTimeUntil(notice.expires_at);

  function dismiss() {
    const next = [...dismissedIds, notice.notice_id].slice(-20);
    setDismissedIds(next);
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
  }

  return (
    <div
      data-testid="system-notice-banner"
      className={`w-full ${s.border} ${s.bg} ${s.text} border-b px-4 py-2 flex items-center gap-3 font-mono text-xs`}
    >
      <Warning size={14} weight="fill" className={s.icon} />
      <div className="flex-1 tracking-wide" data-testid="system-notice-message">
        {notice.message}
        {rel && (
          <span className="ml-2 text-alloy/80" data-testid="system-notice-countdown">
            · {rel}
          </span>
        )}
      </div>
      <button
        data-testid="system-notice-dismiss"
        onClick={dismiss}
        aria-label="Dismiss notice"
        className={`${s.text} opacity-60 hover:opacity-100 transition-opacity`}
      >
        <X size={12} weight="bold" />
      </button>
    </div>
  );
}
