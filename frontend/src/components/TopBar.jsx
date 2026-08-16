import { useState, useEffect } from "react";
import { Power, ShieldCheck, Eye, EyeSlash, Plus, GearSix, Question, Lock, LockOpen, Trash, FloppyDisk, ArrowClockwise } from "@phosphor-icons/react";
import AmbientPulse from "@/components/AmbientPulse";
import { useAuth } from "@/context/AuthContext";
import SettingsModal from "@/components/SettingsModal";
import { getPrivateMode, setPrivateMode, deleteProject, snapshotProject, restoreProject, listSnapshots } from "@/lib/api";

export default function TopBar({
  user, projects, activeProject, onProjectChange, onNewProject,
  gauntletStatus, previewOpen, onTogglePreview, onOpenTutorial,
  onProjectDeleted, onAmbientAskJ,
}) {
  const { signOut } = useAuth();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [privateOn, setPrivateOn] = useState(false);
  const [ollamaReady, setOllamaReady] = useState(false);
  const [pmBusy, setPmBusy] = useState(false);
  const [pmError, setPmError] = useState(null);
  // Snapshot state — persisted per-project via listSnapshots
  const [snapMeta, setSnapMeta] = useState(null); // {ts, bytes, hash}
  const [snapBusy, setSnapBusy] = useState(false);
  const [snapMsg, setSnapMsg] = useState(null);   // transient banner
  const [savePulse, setSavePulse] = useState(0);  // key increments on every save → CSS pulse retriggers

  async function refreshSnapshotMeta(projectId) {
    if (!projectId) { setSnapMeta(null); return; }
    try {
      const r = await listSnapshots(projectId, 1);
      setSnapMeta(r?.latest || null);
    } catch { /* silent — snapshot layer is optional infra */ }
  }
  useEffect(() => {
    refreshSnapshotMeta(activeProject?.project_id);
  }, [activeProject?.project_id]);

  function relTime(iso) {
    if (!iso) return "never";
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0 || Number.isNaN(ms)) return "never";
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  async function handleSnapshot() {
    if (!activeProject || snapBusy) return;
    setSnapBusy(true); setSnapMsg(null);
    try {
      const r = await snapshotProject(activeProject.project_id);
      setSnapMsg(r.unchanged ? "// nothing to save" : `// saved · ${Math.round((r.bytes || 0) / 1024)} KB`);
      setSavePulse((n) => n + 1);
      refreshSnapshotMeta(activeProject.project_id);
    } catch (e) {
      setSnapMsg(`// save failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setSnapBusy(false);
      setTimeout(() => setSnapMsg(null), 3500);
    }
  }

  async function handleRestore() {
    if (!activeProject || snapBusy) return;
    const ok = window.confirm(
      `Restore workspace to last snapshot?\n\nThis WIPES current on-disk files and re-hydrates from the cloud snapshot taken ${relTime(snapMeta?.ts)}. Unsaved local changes will be lost.`
    );
    if (!ok) return;
    setSnapBusy(true); setSnapMsg(null);
    try {
      const r = await restoreProject(activeProject.project_id);
      setSnapMsg(`// restored · ${r.files} files`);
      // Nudge the IDE to refetch its tree/state
      window.dispatchEvent(new CustomEvent("gauntlet:workspace-restored", {
        detail: { project_id: activeProject.project_id },
      }));
    } catch (e) {
      setSnapMsg(`// restore failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setSnapBusy(false);
      setTimeout(() => setSnapMsg(null), 4500);
    }
  }

  async function refreshPrivate() {
    try {
      const r = await getPrivateMode();
      setPrivateOn(!!r.enabled);
      setOllamaReady(!!r.ollama_ready);
    } catch { /* ignore */ }
  }
  useEffect(() => { refreshPrivate(); }, []);
  // Re-poll after Settings closes (user may have just linked Ollama)
  useEffect(() => { if (!settingsOpen) refreshPrivate(); }, [settingsOpen]);

  async function togglePrivate() {
    if (pmBusy) return;
    const next = !privateOn;
    if (next && !ollamaReady) {
      setPmError("Link your local server first");
      setSettingsOpen(true);
      setTimeout(() => setPmError(null), 4000);
      return;
    }
    setPmBusy(true);
    try {
      const r = await setPrivateMode(next);
      setPrivateOn(!!r.enabled);
    } catch (e) {
      setPmError(e?.response?.data?.detail || "Toggle failed");
      setTimeout(() => setPmError(null), 4000);
    } finally { setPmBusy(false); }
  }

  const score = gauntletStatus?.score ?? 5;
  const passColor = score >= 4 ? "var(--viridian)" : score >= 2 ? "var(--orange)" : "#FF2D55";

  return (
    <div className="h-12 border-b border-cyan/10 bg-midnight/90 flex items-center px-2 sm:px-3 gap-2 sm:gap-4 relative z-30" data-testid="top-bar">
      <div className="flex items-center gap-2">
        <div className="h-6 w-6 border border-cyan/60 bg-cyan/10 flex items-center justify-center font-display text-cyan text-[0.65rem]" data-testid="topbar-brand-mark">J</div>
        <div className="hidden sm:block font-display text-[0.7rem] tracking-[0.3em] text-cyan">GAUNTLET</div>
        <div className="hidden md:block font-mono text-[0.6rem] text-alloy">v1.0</div>
      </div>

      {/* Project switcher */}
      <div className="flex items-center gap-1 sm:gap-2 min-w-0">
        <select
          data-testid="project-switcher"
          value={activeProject?.project_id || ""}
          onChange={(e) => {
            const p = projects.find((x) => x.project_id === e.target.value);
            if (p) onProjectChange(p);
          }}
          className="bg-steel border border-cyan/20 text-gridwhite font-mono text-xs px-2 py-1 max-w-[8rem] sm:max-w-none truncate"
        >
          {projects.map((p) => (
            <option key={p.project_id} value={p.project_id}>{p.name}</option>
          ))}
        </select>
        {creating ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (newName.trim()) {
                onNewProject(newName.trim());
                setNewName("");
                setCreating(false);
              }
            }}
            className="flex items-center gap-1"
          >
            <input
              autoFocus
              data-testid="new-project-input"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="shard-name"
              className="bg-steel border border-cyan/30 text-gridwhite font-mono text-xs px-2 py-1 w-28"
              onBlur={() => setCreating(false)}
            />
          </form>
        ) : (
          <>
            <button
              data-testid="new-project-button"
              title="New project"
              onClick={() => setCreating(true)}
              className="text-alloy hover:text-cyan transition-colors"
            >
              <Plus size={16} weight="bold" />
            </button>
            {activeProject && onProjectDeleted && (
              <button
                data-testid="delete-project-button"
                title={`Delete project "${activeProject.name}" (workspace files; chronicle is preserved)`}
                onClick={async () => {
                  const name = activeProject.name || activeProject.project_id;
                  const confirm = window.prompt(
                    `Type the project name to permanently delete:\n\n${name}\n\nThis removes the workspace files. Chat history and chronicle entries are kept for audit.`
                  );
                  if (confirm !== name) return;
                  try {
                    await deleteProject(activeProject.project_id);
                    onProjectDeleted(activeProject.project_id);
                  } catch (e) {
                    window.alert(`Delete failed: ${e?.response?.data?.detail || e.message}`);
                  }
                }}
                className="text-alloy hover:text-orange transition-colors"
              >
                <Trash size={14} weight="bold" />
              </button>
            )}
            {/* Workspace persistence — hybrid auto (every 5m + on session end)
                + manual (these buttons). Users can rely on either. */}
            {activeProject && (
              <>
                <span className="w-px h-4 bg-cyan/15 mx-0.5" />
                <button
                  data-testid="workspace-save-button"
                  disabled={snapBusy}
                  onClick={handleSnapshot}
                  title={snapMeta?.ts
                    ? `Save workspace to cloud (last saved ${relTime(snapMeta.ts)})`
                    : "Save workspace to cloud — required to survive redeploys"}
                  className="relative text-alloy hover:text-cyan transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <FloppyDisk size={14} weight={snapMeta?.ts ? "regular" : "fill"} />
                  {savePulse > 0 && (
                    <span
                      key={savePulse}
                      data-testid="workspace-save-pulse"
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 -m-1 rounded-full save-pulse"
                    />
                  )}
                </button>
                <button
                  data-testid="workspace-restore-button"
                  disabled={snapBusy || !snapMeta?.ts}
                  onClick={handleRestore}
                  title={snapMeta?.ts
                    ? `Restore workspace from last snapshot (${relTime(snapMeta.ts)})`
                    : "No snapshot exists yet — press SAVE first"}
                  className="text-alloy hover:text-amber transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ArrowClockwise size={13} weight="bold" />
                </button>
                <span
                  data-testid="workspace-last-saved"
                  className="hidden md:inline font-mono text-[0.55rem] tracking-widest text-alloy/70 ml-1"
                  title={snapMeta?.ts ? `last snapshot: ${snapMeta.ts}` : "never saved"}
                >
                  {snapMsg || (snapMeta?.ts ? `saved ${relTime(snapMeta.ts)}` : "not saved")}
                </span>
              </>
            )}
          </>
        )}
      </div>

      {/* Gauntlet HUD */}
      <div className="flex items-center gap-2 ml-auto" data-testid="gauntlet-hud">
        <ShieldCheck size={14} style={{ color: passColor }} weight="fill" />
        <span className="hidden md:inline font-display text-[0.7rem] tracking-[0.25em] text-alloy">GAUNTLET</span>
        <div className="hidden sm:flex gap-1">
          {[0,1,2,3,4].map((i) => (
            <span
              key={i}
              className="w-2 h-2"
              style={{
                background: i < score ? passColor : "rgba(125,133,151,0.25)",
                borderRadius: 1,
              }}
            />
          ))}
        </div>
        <span className="font-mono text-[0.7rem] text-cyan">{score}/5</span>
      </div>

      {/* Private Mode toggle */}
      <button
        data-testid="private-mode-toggle"
        onClick={togglePrivate}
        disabled={pmBusy}
        title={
          privateOn
            ? "PRIVATE — only your local server runs. Click to allow cloud + Universal Key again."
            : ollamaReady
              ? "PUBLIC — Universal Key + cloud BYOK + local server. Click to lock to local only."
              : "Link a local server in Settings to enable Private Mode."
        }
        className={`inline-flex items-center gap-1.5 px-2 py-1 border font-display text-[0.65rem] tracking-[0.2em] transition-colors ${
          privateOn
            ? "border-cyan text-cyan bg-cyan/10 shadow-[0_0_12px_rgba(0,217,255,0.3)]"
            : ollamaReady
              ? "border-cyan/30 text-alloy hover:text-cyan hover:border-cyan/60"
              : "border-alloy/20 text-alloy/60 hover:text-alloy"
        } ${pmBusy ? "opacity-50" : ""}`}
      >
        {privateOn ? <Lock size={12} weight="fill" /> : <LockOpen size={12} weight="regular" />}
        <span data-testid="private-mode-label">{privateOn ? "PRIVATE" : "PUBLIC"}</span>
      </button>

      {pmError && (
        <div
          className="absolute top-12 right-3 mt-1 panel px-3 py-2 font-mono text-[0.7rem] text-orange border border-orange/40"
          data-testid="private-mode-error"
        >
          {pmError}
        </div>
      )}

      {/* JARVIS heartbeat pulse */}
      <AmbientPulse onAskJ={onAmbientAskJ} />

      <button
        data-testid="toggle-preview"
        onClick={onTogglePreview}
        className="btn-ghost !px-2 sm:!px-3"
      >
        {previewOpen ? <EyeSlash size={14} /> : <Eye size={14} />}
        <span className="hidden sm:inline">{previewOpen ? "HIDE" : "PREVIEW"}</span>
      </button>

      <div className="hidden sm:block h-6 w-px bg-cyan/15"></div>
      {onOpenTutorial && (
        <button
          data-testid="help-button"
          onClick={onOpenTutorial}
          title="Replay tutorial"
          className="text-alloy hover:text-cyan transition-colors"
        >
          <Question size={14} weight="bold" />
        </button>
      )}
      <button
        data-testid="settings-button"
        onClick={() => setSettingsOpen(true)}
        title="Settings · Provider keys"
        className="text-alloy hover:text-cyan transition-colors"
      >
        <GearSix size={14} weight="bold" />
      </button>
      <div className="flex items-center gap-2">
        {user?.picture ? (
          <img src={user.picture} alt={user.name} className="h-6 w-6 rounded-full" />
        ) : (
          <div className="h-6 w-6 rounded-full bg-steel border border-cyan/30 flex items-center justify-center font-mono text-[0.65rem] text-cyan">
            {(user?.name || "?")[0].toUpperCase()}
          </div>
        )}
        <span className="font-mono text-xs text-alloy hidden md:block">{user?.email}</span>
        <button
          data-testid="logout-button"
          onClick={signOut}
          title="Sign out"
          className="text-alloy hover:text-orange transition-colors"
        >
          <Power size={14} weight="bold" />
        </button>
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
