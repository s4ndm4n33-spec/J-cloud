import { useState } from "react";
import { Power, ShieldCheck, Eye, EyeSlash, Plus, GearSix, Question } from "@phosphor-icons/react";
import { useAuth } from "@/context/AuthContext";
import SettingsModal from "@/components/SettingsModal";

const LOGO_URL =
  "https://static.prod-images.emergentagent.com/jobs/9f05830c-98fc-45b2-9802-59ed95a81ea4/images/19195be13f453611a4e6f74609c0e5103632c06cef4ee0bd02591a172f1b10c1.png";

export default function TopBar({
  user, projects, activeProject, onProjectChange, onNewProject,
  gauntletStatus, previewOpen, onTogglePreview, onOpenTutorial,
}) {
  const { signOut } = useAuth();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const score = gauntletStatus?.score ?? 5;
  const passColor = score >= 4 ? "var(--viridian)" : score >= 2 ? "var(--orange)" : "#FF2D55";

  return (
    <div className="h-12 border-b border-cyan/10 bg-midnight/90 flex items-center px-2 sm:px-3 gap-2 sm:gap-4 relative z-30" data-testid="top-bar">
      <div className="flex items-center gap-2">
        <img src={LOGO_URL} alt="Sovereign Shards" className="h-6 w-6" />
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
          <button
            data-testid="new-project-button"
            title="New project"
            onClick={() => setCreating(true)}
            className="text-alloy hover:text-cyan transition-colors"
          >
            <Plus size={16} weight="bold" />
          </button>
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
