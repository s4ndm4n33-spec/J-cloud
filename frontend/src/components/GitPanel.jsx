import { useEffect, useState } from "react";
import { gitStatus, gitCommit, gitLog } from "@/lib/api";

export default function GitPanel({ projectId, onRefresh }) {
  const [status, setStatus] = useState({ branch: "main", files: [] });
  const [log, setLog] = useState([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [s, l] = await Promise.all([gitStatus(projectId), gitLog(projectId)]);
    setStatus(s); setLog(l.commits);
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [projectId]);

  async function commit() {
    if (!msg.trim()) return;
    setBusy(true);
    try {
      await gitCommit(projectId, msg, ["."]);
      setMsg("");
      await refresh();
      onRefresh?.();
    } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-col h-full" data-testid="git-panel">
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center justify-between">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">GIT</div>
        <div className="font-mono text-[0.65rem] text-alloy">⌥ {status.branch}</div>
      </div>

      <div className="p-3 border-b border-cyan/10">
        <textarea
          data-testid="git-commit-message"
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          placeholder="commit message"
          rows={2}
          className="w-full bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs resize-none"
        />
        <button
          data-testid="git-commit-button"
          disabled={busy || !msg.trim() || !status.files.length}
          onClick={commit}
          className="btn-solid w-full mt-2 justify-center"
        >COMMIT ALL</button>
      </div>

      <div className="px-3 py-2 border-b border-cyan/10">
        <div className="font-mono text-[0.65rem] text-alloy mb-1">// CHANGES ({status.files.length})</div>
        {status.files.length === 0 && (
          <div className="font-mono text-[0.7rem] text-alloy/60">// clean</div>
        )}
        {status.files.map((f, i) => (
          <div key={i} className="font-mono text-[0.7rem] flex gap-2">
            <span className="text-orange w-6">{f.status}</span>
            <span className="text-gridwhite/80 truncate">{f.path}</span>
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin px-3 py-2">
        <div className="font-mono text-[0.65rem] text-alloy mb-1">// LOG</div>
        {log.map((c, i) => (
          <div key={i} className="font-mono text-[0.7rem] py-0.5">
            <span className="text-cyan">{c.hash}</span>{" "}
            <span className="text-gridwhite/80">{c.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
