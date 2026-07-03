import { useEffect, useState, useCallback } from "react";
import { Brain, MagnifyingGlass, Check, X, Trash, Sparkle, LinkSimple } from "@phosphor-icons/react";
import {
  getKnowledgeStats, getKnowledgeFacts, deleteKnowledgeFact,
  getKnowledgeProposals, resolveKnowledgeProposal,
  knowledgeSearch, getKnowledgeCategories,
} from "@/lib/api";

const NAV = [
  { key: "facts", label: "FACTS", Icon: Brain },
  { key: "proposals", label: "PROPOSALS", Icon: Sparkle },
  { key: "search", label: "TEACH", Icon: MagnifyingGlass },
];

export default function KnowledgePanel() {
  const [view, setView] = useState("facts");
  const [stats, setStats] = useState(null);
  const [categories, setCategories] = useState([]);

  const refreshStats = useCallback(async () => {
    try {
      const s = await getKnowledgeStats();
      setStats(s);
    } catch { /* signed out */ }
  }, []);

  useEffect(() => {
    refreshStats();
    getKnowledgeCategories().then((r) => setCategories(r.categories || [])).catch(() => {});
  }, [refreshStats]);

  return (
    <div className="h-full flex flex-col bg-midnight" data-testid="mind-panel">
      <div className="border-b border-cyan/10 px-3 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={14} weight="fill" className="text-cyan" />
          <span className="font-display text-[0.7rem] tracking-[0.25em] text-gridwhite">J:MIND</span>
        </div>
        {stats && (
          <div className="font-mono text-[0.6rem] text-alloy flex items-center gap-3" data-testid="mind-stats">
            <span><span className="text-cyan">{stats.total_facts}</span> facts</span>
            <span><span className="text-amber">{stats.proposals.pending}</span> pending</span>
          </div>
        )}
      </div>

      <div className="flex border-b border-cyan/10">
        {NAV.map((n) => {
          const active = view === n.key;
          return (
            <button
              key={n.key}
              data-testid={`mind-nav-${n.key}`}
              onClick={() => setView(n.key)}
              className={`flex-1 py-1.5 text-[0.6rem] font-display tracking-[0.2em] flex items-center justify-center gap-1.5 ${
                active ? "text-cyan border-b border-cyan bg-steel" : "text-alloy hover:text-gridwhite"
              }`}
            >
              <n.Icon size={11} weight={active ? "fill" : "regular"} />
              {n.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {view === "facts" && <FactsList categories={categories} onChange={refreshStats} />}
        {view === "proposals" && <ProposalsList onResolved={refreshStats} />}
        {view === "search" && <TeachTab onLearned={refreshStats} />}
      </div>
    </div>
  );
}

function FactsList({ categories, onChange }) {
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [facts, setFacts] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getKnowledgeFacts({ category: category || undefined, q: q || undefined });
      setFacts(r.facts || []);
    } finally { setLoading(false); }
  }, [category, q]);

  useEffect(() => { load(); }, [load]);

  const remove = async (id) => {
    if (!window.confirm("Delete this fact from J:MIND?")) return;
    await deleteKnowledgeFact(id);
    load();
    onChange?.();
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-2 flex gap-1.5 border-b border-cyan/10">
        <input
          data-testid="mind-facts-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="search remembered facts..."
          className="flex-1 bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs text-gridwhite"
        />
        <select
          data-testid="mind-category-filter"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="bg-steel border border-cyan/20 px-1.5 py-1 font-mono text-[0.65rem] text-gridwhite"
        >
          <option value="">ALL</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {loading && <div className="text-alloy font-mono text-xs">loading...</div>}
        {!loading && facts.length === 0 && (
          <div className="text-alloy font-mono text-xs px-1 py-3 text-center">
            no facts yet. ask J something that requires a web search — she'll auto-remember.
          </div>
        )}
        {facts.map((f) => (
          <div key={f.id} className="border border-cyan/15 bg-steel/40 p-2 group" data-testid={`mind-fact-${f.id}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="font-display text-[0.7rem] text-gridwhite tracking-wide">{f.title}</div>
              <button
                data-testid={`mind-delete-${f.id}`}
                onClick={() => remove(f.id)}
                className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300"
                title="delete"
              >
                <Trash size={12} />
              </button>
            </div>
            <div className="font-mono text-[0.65rem] text-alloy mt-1 leading-relaxed">{f.body}</div>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              <span className="font-mono text-[0.55rem] text-cyan bg-cyan/10 px-1.5 py-0.5">{f.category}</span>
              {(f.tags || []).slice(0, 4).map((t) => (
                <span key={t} className="font-mono text-[0.55rem] text-alloy">#{t}</span>
              ))}
              {f.source_url && (
                <a
                  href={f.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto font-mono text-[0.55rem] text-cyan/70 hover:text-cyan flex items-center gap-1"
                  data-testid={`mind-src-${f.id}`}
                >
                  <LinkSimple size={10} /> src
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProposalsList({ onResolved }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getKnowledgeProposals("pending");
      setItems(r.proposals || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const act = async (id, action) => {
    await resolveKnowledgeProposal(id, action);
    load();
    onResolved?.();
  };

  return (
    <div className="h-full overflow-y-auto p-2 space-y-2">
      {loading && <div className="text-alloy font-mono text-xs">loading...</div>}
      {!loading && items.length === 0 && (
        <div className="text-alloy font-mono text-xs px-1 py-3 text-center">
          no pending proposals. J proposes when she learns something durable from you.
        </div>
      )}
      {items.map((p) => (
        <div key={p.id} className="border border-amber/30 bg-amber/5 p-2" data-testid={`mind-proposal-${p.id}`}>
          <div className="font-display text-[0.7rem] text-gridwhite tracking-wide">{p.title}</div>
          <div className="font-mono text-[0.65rem] text-alloy mt-1 leading-relaxed">{p.body}</div>
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[0.55rem] text-amber bg-amber/10 px-1.5 py-0.5">{p.category}</span>
              {(p.tags || []).slice(0, 3).map((t) => (
                <span key={t} className="font-mono text-[0.55rem] text-alloy">#{t}</span>
              ))}
            </div>
            <div className="flex gap-1">
              <button
                data-testid={`mind-accept-${p.id}`}
                onClick={() => act(p.id, "accept")}
                className="px-2 py-0.5 border border-cyan/40 text-cyan text-[0.55rem] font-display tracking-widest hover:bg-cyan/10 flex items-center gap-1"
              >
                <Check size={10} /> ACCEPT
              </button>
              <button
                data-testid={`mind-reject-${p.id}`}
                onClick={() => act(p.id, "reject")}
                className="px-2 py-0.5 border border-red-500/40 text-red-400 text-[0.55rem] font-display tracking-widest hover:bg-red-500/10 flex items-center gap-1"
              >
                <X size={10} /> REJECT
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TeachTab({ onLearned }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!query.trim() || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await knowledgeSearch(query.trim(), { max_results: 5, learn: true });
      setResult(r);
      onLearned?.();
    } catch (e) {
      setResult({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-2 border-b border-cyan/10 space-y-1.5">
        <div className="font-mono text-[0.6rem] text-alloy leading-relaxed">
          Search the live web via Tavily. Every result auto-distills into J:MIND —
          future J will remember what she learned here.
        </div>
        <div className="flex gap-1.5">
          <input
            data-testid="mind-teach-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="e.g. Nissan Versa 2015 door lock actuator torque spec"
            className="flex-1 bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs text-gridwhite"
          />
          <button
            data-testid="mind-teach-run"
            onClick={run}
            disabled={busy || !query.trim()}
            className="btn-solid px-3"
          >
            {busy ? "..." : "SEARCH"}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {result?.error && (
          <div className="border border-red-500/40 bg-red-500/5 p-2 font-mono text-xs text-red-300">
            {result.error}
          </div>
        )}
        {result?.answer && (
          <div className="border border-cyan/30 bg-cyan/5 p-2">
            <div className="font-display text-[0.6rem] tracking-[0.25em] text-cyan mb-1">ANSWER</div>
            <div className="font-mono text-[0.7rem] text-gridwhite leading-relaxed">{result.answer}</div>
          </div>
        )}
        {result?._learn && (
          <div className="font-mono text-[0.6rem] text-alloy">
            learned <span className="text-cyan">{result._learn.learned}</span> new fact(s) —
            category: <span className="text-cyan">{result._learn.category}</span>
          </div>
        )}
        {(result?.results || []).map((r, i) => (
          <div key={i} className="border border-cyan/15 bg-steel/40 p-2">
            <a href={r.url} target="_blank" rel="noopener noreferrer" className="font-display text-[0.7rem] text-cyan hover:underline">
              {r.title}
            </a>
            <div className="font-mono text-[0.6rem] text-alloy mt-1 leading-relaxed">{r.content}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
