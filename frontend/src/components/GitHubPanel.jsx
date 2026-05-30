import { useEffect, useState, Component } from "react";
import { GithubLogo, CloudArrowUp, CloudArrowDown, GitPullRequest, Plus, ArrowSquareOut, X } from "@phosphor-icons/react";
import {
  githubStatus, githubConnectPAT, githubDisconnect, githubRepos, githubClone,
  githubCreateRepo, githubPush, githubPull, githubPR,
  gitStatus, gitCommit,
} from "@/lib/api";

class PanelErrorBoundary extends Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { console.error("GitHubPanel crashed:", err, info); }
  render() {
    if (this.state.err) {
      return (
        <div className="p-3 font-mono text-[0.7rem] text-orange" data-testid="github-panel-error">
          // GitHub panel hit an error. Reload to retry.
          <pre className="text-[0.6rem] mt-2 whitespace-pre-wrap break-words">{String(this.state.err)}</pre>
          <button onClick={() => this.setState({ err: null })} className="btn-ghost mt-2 text-[0.65rem]">RETRY</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function GitHubPanel(props) {
  return (
    <PanelErrorBoundary>
      <GitHubPanelInner {...props} />
    </PanelErrorBoundary>
  );
}

function GitHubPanelInner({ projectId, onRefresh, onProjectCloned }) {
  const [gh, setGh] = useState({ connected: false });
  const [local, setLocal] = useState({ branch: "main", files: [] });
  const [view, setView] = useState("dashboard"); // dashboard | connect | repos | new
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [commitMsg, setCommitMsg] = useState("");

  function flash(m) { setToast(m); setTimeout(() => setToast(null), 2200); }

  async function refresh() {
    let s = { connected: false };
    let ls = { branch: "main", files: [] };
    try { s = await githubStatus(); }
    catch (e) { console.warn("githubStatus failed", e); }
    if (projectId) {
      try { ls = await gitStatus(projectId); }
      catch (e) { console.warn("gitStatus failed", e); }
    }
    setGh(s); setLocal(ls);
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [projectId]);

  async function commit() {
    if (!commitMsg.trim()) return;
    setBusy(true);
    try {
      await gitCommit(projectId, commitMsg, ["."]);
      setCommitMsg(""); flash("Committed");
      await refresh(); onRefresh?.();
    } finally { setBusy(false); }
  }

  async function push() {
    setBusy(true);
    try {
      const r = await githubPush(projectId, local.branch);
      flash(r.ok ? "Pushed" : (r.stderr?.slice(0, 80) || "Push failed"));
      await refresh();
    } catch (e) {
      flash(e?.response?.data?.detail || "Push failed");
    } finally { setBusy(false); }
  }

  async function pull() {
    setBusy(true);
    try {
      const r = await githubPull(projectId, local.branch);
      flash(r.ok ? "Pulled" : (r.stderr?.slice(0, 80) || "Pull failed"));
      onRefresh?.();
    } catch (e) {
      flash(e?.response?.data?.detail || "Pull failed");
    } finally { setBusy(false); }
  }

  async function openPR() {
    setBusy(true);
    try {
      const r = await githubPR(projectId, { title: commitMsg || "Sovereign Gauntlet PR", base: "main" });
      if (r.pr) { flash(`PR #${r.pr.number} opened`); window.open(r.pr.html_url, "_blank"); }
    } catch (e) {
      flash(e?.response?.data?.detail || "PR failed");
    } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-col h-full" data-testid="github-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10">
        <div className="flex items-center gap-1.5">
          <GithubLogo size={14} className="text-cyan" weight="fill" />
          <div className="font-display text-cyan tracking-widest text-[0.65rem]">GITHUB</div>
        </div>
        <div className="font-mono text-[0.65rem] text-alloy">⌥ {local.branch}</div>
      </div>

      {/* Connection state */}
      {!gh.connected ? (
        view === "connect" ? (
          <ConnectForm
            onDone={async () => { await refresh(); setView("dashboard"); flash("Connected"); }}
            onCancel={() => setView("dashboard")}
            flash={flash}
          />
        ) : (
          <div className="p-3">
            <div className="font-mono text-[0.7rem] text-alloy mb-2">
              // Not connected. Paste a GitHub Personal Access Token to enable the full suite.
            </div>
            <button
              data-testid="gh-connect-button"
              onClick={() => setView("connect")}
              className="btn-solid w-full justify-center"
            >
              <GithubLogo size={12} weight="fill" /> CONNECT TOKEN
            </button>
            <div className="mt-2 font-mono text-[0.6rem] text-alloy">
              Scopes needed: <span className="text-cyan">repo</span>, <span className="text-cyan">read:user</span>
            </div>
            <a
              href="https://github.com/settings/tokens/new?scopes=repo,read:user&description=Gauntlet%20DevSpace"
              target="_blank" rel="noreferrer"
              className="font-mono text-[0.65rem] text-cyan hover:underline mt-1 inline-block"
            >&gt; create one on github.com</a>
          </div>
        )
      ) : (
        <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-2">
          {gh.avatar_url ? <img src={gh.avatar_url} alt={gh.login} className="h-6 w-6 rounded-full" /> : null}
          <div className="flex-1 min-w-0">
            <div className="font-mono text-xs text-gridwhite truncate">{gh.login}</div>
            <div className="font-mono text-[0.6rem] text-alloy">{gh.masked}</div>
          </div>
          <button
            data-testid="gh-disconnect"
            onClick={async () => { await githubDisconnect(); await refresh(); flash("Disconnected"); }}
            className="text-alloy hover:text-orange" title="Disconnect"
          ><X size={12} weight="bold" /></button>
        </div>
      )}

      {gh.connected && (
        <>
          {/* Action grid */}
          <div className="px-3 py-2 grid grid-cols-2 gap-1.5 border-b border-cyan/10">
            <button data-testid="gh-clone" onClick={() => setView("repos")} className="btn-ghost text-[0.65rem] justify-center">
              <CloudArrowDown size={12} /> CLONE
            </button>
            <button data-testid="gh-new-repo" onClick={() => setView("new")} className="btn-ghost text-[0.65rem] justify-center" disabled={!projectId}>
              <Plus size={12} /> NEW REPO
            </button>
            <button data-testid="gh-push" onClick={push} disabled={busy || !projectId} className="btn-ghost text-[0.65rem] justify-center">
              <CloudArrowUp size={12} /> PUSH
            </button>
            <button data-testid="gh-pull" onClick={pull} disabled={busy || !projectId} className="btn-ghost text-[0.65rem] justify-center">
              <CloudArrowDown size={12} /> PULL
            </button>
            <button data-testid="gh-pr" onClick={openPR} disabled={busy || !projectId} className="btn-ghost text-[0.65rem] justify-center col-span-2">
              <GitPullRequest size={12} /> OPEN PR
            </button>
          </div>

          {view === "repos" && (
            <RepoBrowser
              onClone={async (r) => {
                setBusy(true);
                try {
                  const p = await githubClone({ clone_url: r.clone_url, full_name: r.full_name, name: r.name });
                  flash(`Cloned ${r.full_name}`);
                  onProjectCloned?.(p);
                  setView("dashboard");
                } catch (e) {
                  flash(e?.response?.data?.detail || "Clone failed");
                } finally { setBusy(false); }
              }}
              onClose={() => setView("dashboard")}
              busy={busy}
            />
          )}

          {view === "new" && projectId && (
            <NewRepoForm
              onCreate={async (payload) => {
                setBusy(true);
                try {
                  const r = await githubCreateRepo(projectId, payload);
                  if (r.repo) { flash(`Repo created`); window.open(r.repo.html_url, "_blank"); }
                  await refresh();
                  setView("dashboard");
                } catch (e) {
                  flash(e?.response?.data?.detail || "Create failed");
                } finally { setBusy(false); }
              }}
              onCancel={() => setView("dashboard")}
            />
          )}
        </>
      )}

      {/* Commit + local changes */}
      <div className="px-3 py-2 border-t border-cyan/10">
        <textarea
          data-testid="gh-commit-message"
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
          placeholder="commit message"
          rows={2}
          className="w-full bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs resize-none"
        />
        <button
          data-testid="gh-commit-button"
          disabled={busy || !commitMsg.trim() || !local.files.length}
          onClick={commit}
          className="btn-solid w-full mt-2 justify-center text-[0.7rem]"
        >COMMIT ALL</button>
      </div>

      <div className="px-3 py-2 border-t border-cyan/10 flex-1 overflow-auto scrollbar-thin">
        <div className="font-mono text-[0.65rem] text-alloy mb-1">// CHANGES ({local.files.length})</div>
        {local.files.length === 0 && (
          <div className="font-mono text-[0.7rem] text-alloy/60">// clean tree</div>
        )}
        {local.files.map((f, i) => (
          <div key={i} className="font-mono text-[0.7rem] flex gap-2">
            <span className="text-orange w-6">{f.status}</span>
            <span className="text-gridwhite/80 truncate">{f.path}</span>
          </div>
        ))}
      </div>

      {toast && (
        <div className="absolute left-3 bottom-3 panel px-3 py-1 font-mono text-[0.7rem] text-cyan z-30" data-testid="github-toast">
          {toast}
        </div>
      )}
    </div>
  );
}

function ConnectForm({ onDone, onCancel, flash }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function go() {
    setBusy(true); setError("");
    try { await githubConnectPAT(token.trim()); onDone(); }
    catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Invalid token";
      setError(String(detail));
      flash("Token rejected — see panel for details");
    }
    finally { setBusy(false); }
  }
  return (
    <div className="p-3 space-y-2" data-testid="gh-connect-form">
      <div className="font-mono text-[0.7rem] text-cyan">// PAT (encrypted at rest)</div>
      <input
        autoFocus
        type="password"
        placeholder="ghp_… or github_pat_…"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") go(); }}
        className="w-full bg-steel border border-cyan/30 px-2 py-1.5 font-mono text-xs text-gridwhite"
        data-testid="gh-token-input"
      />
      {error && (
        <div className="p-2 border border-orange/40 bg-orange/5 font-mono text-[0.65rem] text-orange whitespace-pre-wrap break-words max-h-32 overflow-auto" data-testid="gh-token-error">
          {error}
        </div>
      )}
      <div className="font-mono text-[0.6rem] text-alloy leading-relaxed">
        Required for <span className="text-cyan">classic</span> PAT: <span className="text-cyan">repo</span> + <span className="text-cyan">read:user</span> scopes.
        <br />
        For <span className="text-cyan">fine-grained</span> PAT: <span className="text-cyan">Contents R/W</span> + <span className="text-cyan">Metadata R</span> + <span className="text-cyan">Pull requests R/W</span>, with target repos selected under "Repository access".
      </div>
      <div className="flex gap-2 flex-wrap">
        <a
          href="https://github.com/settings/tokens/new?scopes=repo,read:user&description=Gauntlet%20DevSpace"
          target="_blank" rel="noreferrer"
          className="font-mono text-[0.6rem] text-cyan hover:underline"
        >&gt; create classic PAT</a>
        <a
          href="https://github.com/settings/personal-access-tokens/new"
          target="_blank" rel="noreferrer"
          className="font-mono text-[0.6rem] text-cyan hover:underline"
        >&gt; create fine-grained PAT</a>
      </div>
      <div className="flex gap-1.5">
        <button onClick={onCancel} className="btn-ghost flex-1 justify-center text-[0.7rem]">CANCEL</button>
        <button onClick={go} disabled={busy || token.trim().length < 20} className="btn-solid flex-1 justify-center text-[0.7rem]" data-testid="gh-token-save">
          {busy ? "VERIFYING…" : "CONNECT"}
        </button>
      </div>
    </div>
  );
}

function RepoBrowser({ onClone, onClose, busy }) {
  const [repos, setRepos] = useState([]);
  const [q, setQ] = useState("");
  useEffect(() => { githubRepos(1).then((r) => setRepos(r.repos || [])).catch(() => {}); }, []);
  const filtered = repos.filter((r) => r.full_name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="p-2 border-b border-cyan/10 max-h-64 overflow-auto scrollbar-thin" data-testid="gh-repo-browser">
      <div className="flex items-center gap-1.5 mb-2">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="filter repos…"
          className="flex-1 bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs"
        />
        <button onClick={onClose} className="text-alloy hover:text-orange"><X size={12} /></button>
      </div>
      {filtered.map((r) => (
        <div key={r.full_name} className="flex items-center gap-2 py-1 border-b border-cyan/5">
          <div className="flex-1 min-w-0">
            <div className="font-mono text-[0.75rem] text-gridwhite truncate flex items-center gap-1">
              {r.full_name}
              {r.private && <span className="font-mono text-[0.55rem] text-orange">PRIVATE</span>}
            </div>
            <div className="font-mono text-[0.6rem] text-alloy truncate">{r.description || "—"}</div>
          </div>
          <a href={r.html_url} target="_blank" rel="noreferrer" className="text-alloy hover:text-cyan"><ArrowSquareOut size={11} /></a>
          <button onClick={() => onClone(r)} disabled={busy} className="btn-ghost text-[0.6rem] py-0.5 px-2" data-testid={`gh-clone-${r.full_name.replace("/", "-")}`}>
            CLONE
          </button>
        </div>
      ))}
      {!filtered.length && <div className="font-mono text-[0.7rem] text-alloy">// no repos</div>}
    </div>
  );
}

function NewRepoForm({ onCreate, onCancel }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [priv, setPriv] = useState(true);
  return (
    <div className="p-2 border-b border-cyan/10 space-y-2" data-testid="gh-new-repo-form">
      <input
        autoFocus value={name} onChange={(e) => setName(e.target.value)}
        placeholder="repo name" data-testid="gh-new-name"
        className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs"
      />
      <input
        value={desc} onChange={(e) => setDesc(e.target.value)}
        placeholder="description (optional)"
        className="w-full bg-steel border border-cyan/20 px-2 py-1 font-mono text-xs"
      />
      <label className="flex items-center gap-2 font-mono text-[0.7rem] text-alloy">
        <input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
        private
      </label>
      <div className="flex gap-1.5">
        <button onClick={onCancel} className="btn-ghost flex-1 justify-center text-[0.7rem]">CANCEL</button>
        <button onClick={() => onCreate({ name, description: desc, private: priv })} disabled={!name.trim()} className="btn-solid flex-1 justify-center text-[0.7rem]" data-testid="gh-new-create">
          CREATE + PUSH
        </button>
      </div>
    </div>
  );
}
