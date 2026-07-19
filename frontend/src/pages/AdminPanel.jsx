/* Owner-only abuse-flag dashboard.
   Read-only view of `db.moderation_flags`. Anything sensitive is already
   truncated to a 400-char snippet by the backend. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Warning, ArrowClockwise, ArrowLeft } from "@phosphor-icons/react";
import { listAdminFlags, adminFlagsSummary } from "@/lib/api";

const CATEGORY_STYLES = {
  substrate_leak:    { color: "text-orange",   label: "SUBSTRATE" },
  outbound_refused:  { color: "text-cyan",     label: "OUTBOUND"  },
  destructive_block: { color: "text-rose-400", label: "DESTRUCT"  },
};

function fmtTs(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch { return iso; }
}

export default function AdminPanel() {
  const nav = useNavigate();
  const [summary, setSummary] = useState(null);
  const [flags, setFlags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [category, setCategory] = useState("");

  async function load() {
    setLoading(true); setErr("");
    try {
      const [s, f] = await Promise.all([
        adminFlagsSummary(),
        listAdminFlags({ limit: 200, category: category || undefined }),
      ]);
      setSummary(s);
      setFlags(f.flags || []);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 403) setErr("Owner-only. This dashboard is not for you.");
      else setErr(e?.response?.data?.detail || e?.message || "Load failed.");
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [category]);  // eslint-disable-line

  return (
    <div className="min-h-screen bg-void text-gridwhite p-6 font-mono"
         data-testid="admin-panel">
      <header className="flex items-center justify-between mb-6 border-b border-cyan/20 pb-4">
        <div>
          <button
            type="button"
            onClick={() => nav("/ide")}
            className="text-[0.7rem] text-alloy hover:text-cyan flex items-center gap-1 mb-1"
            data-testid="admin-back-btn"
          >
            <ArrowLeft size={11} /> back to IDE
          </button>
          <h1 className="text-2xl tracking-widest text-cyan flex items-center gap-2">
            <Warning size={20} weight="fill" /> ABUSE DASHBOARD
          </h1>
          <div className="text-[0.7rem] text-alloy mt-1">
            Read-only. Reflects the last 7 days of guardrail hits.
          </div>
        </div>
        <button
          type="button"
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-cyan/40 text-cyan text-[0.7rem] tracking-widest hover:bg-cyan/10"
          data-testid="admin-refresh-btn"
          disabled={loading}
        >
          <ArrowClockwise size={11} weight={loading ? "regular" : "bold"} />
          {loading ? "LOADING…" : "REFRESH"}
        </button>
      </header>

      {err && (
        <div className="panel border border-orange/40 bg-orange/5 p-3 text-orange text-sm"
             data-testid="admin-error">
          {err}
        </div>
      )}

      {summary && (
        <section className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6"
                 data-testid="admin-summary">
          <SummaryCard label="TOTAL FLAGS (7d)" value={summary.total_flags} />
          <SummaryCard
            label="BY CATEGORY"
            value={
              <div className="space-y-1">
                {summary.by_category.length === 0
                  ? <span className="text-alloy text-[0.75rem]">— nothing —</span>
                  : summary.by_category.map((c) => (
                      <button
                        key={c.category}
                        onClick={() => setCategory(c.category === category ? "" : c.category)}
                        className={`flex items-center gap-2 text-[0.75rem] w-full ${
                          category === c.category
                            ? "text-cyan"
                            : (CATEGORY_STYLES[c.category]?.color || "text-alloy")
                        } hover:underline`}
                        data-testid={`admin-cat-${c.category}`}
                      >
                        <span className="min-w-[6rem] text-left">
                          {CATEGORY_STYLES[c.category]?.label || c.category}
                        </span>
                        <span className="text-gridwhite">{c.count}</span>
                      </button>
                    ))}
              </div>
            }
          />
          <SummaryCard
            label="TOP OFFENDERS"
            value={
              summary.top_users.length === 0
                ? <span className="text-alloy text-[0.75rem]">— nobody —</span>
                : (
                  <div className="space-y-1">
                    {summary.top_users.slice(0, 5).map((u) => (
                      <div key={u.user_id} className="flex items-center gap-2 text-[0.7rem]">
                        <span className="text-alloy truncate max-w-[10rem]">{u.user_id}</span>
                        <span className="text-orange">{u.count}</span>
                        <span className="text-alloy/60">
                          {u.categories.map((c) => CATEGORY_STYLES[c]?.label || c).join(" · ")}
                        </span>
                      </div>
                    ))}
                  </div>
                )
            }
          />
        </section>
      )}

      <section className="panel border border-cyan/20 bg-void/50">
        <div className="border-b border-cyan/20 px-4 py-2 flex items-center justify-between">
          <span className="text-[0.7rem] tracking-widest text-alloy">
            RECENT FLAGS {category ? `· FILTERED: ${category}` : ""}
          </span>
          {category && (
            <button
              type="button"
              onClick={() => setCategory("")}
              className="text-[0.65rem] text-cyan hover:underline"
              data-testid="admin-clear-filter"
            >
              clear filter
            </button>
          )}
        </div>
        {flags.length === 0 && !loading ? (
          <div className="p-6 text-center text-alloy text-[0.75rem]" data-testid="admin-empty">
            No flags. J is behaving.
          </div>
        ) : (
          <div className="divide-y divide-cyan/10" data-testid="admin-flags-list">
            {flags.map((f, i) => {
              const style = CATEGORY_STYLES[f.category] || { color: "text-alloy", label: f.category };
              return (
                <div key={i} className="p-3 grid grid-cols-12 gap-2 text-[0.72rem] items-start hover:bg-cyan/[0.02]">
                  <div className={`col-span-2 ${style.color} font-bold tracking-widest`}>
                    {style.label}
                  </div>
                  <div className="col-span-3 text-alloy truncate" title={f.user_id}>
                    {f.user_id}
                  </div>
                  <div className="col-span-2 text-alloy/70">{fmtTs(f.ts)}</div>
                  <div className="col-span-2 text-gridwhite truncate" title={f.matched}>
                    {f.matched}
                  </div>
                  <div className="col-span-3 text-alloy/70 truncate" title={f.route}>
                    {f.route}
                  </div>
                  {f.snippet && (
                    <div className="col-span-12 text-alloy/60 text-[0.68rem] pl-2 border-l border-cyan/20 whitespace-pre-wrap break-all">
                      {f.snippet.slice(0, 200)}{f.snippet.length > 200 ? "…" : ""}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function SummaryCard({ label, value }) {
  return (
    <div className="panel border border-cyan/20 bg-void/50 p-4">
      <div className="text-[0.6rem] tracking-widest text-alloy mb-2">{label}</div>
      <div className="text-gridwhite">
        {typeof value === "number" || typeof value === "string"
          ? <span className="text-3xl text-cyan">{value}</span>
          : value}
      </div>
    </div>
  );
}
