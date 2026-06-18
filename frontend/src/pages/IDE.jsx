import { useEffect, useState, useCallback, useRef } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  listProjects, createProject, projectTree, readFile, writeFile,
} from "@/lib/api";
import TopBar from "@/components/TopBar";
import LeftRail from "@/components/LeftRail";
import FileTree from "@/components/FileTree";
import EditorPane from "@/components/EditorPane";
import AICoworker from "@/components/AICoworker";
import TerminalPane from "@/components/TerminalPane";
import ProblemsPanel from "@/components/ProblemsPanel";
import GitHubPanel from "@/components/GitHubPanel";
import LivePreview from "@/components/LivePreview";
import InlineEditModal from "@/components/InlineEditModal";
import HardBlockModal from "@/components/HardBlockModal";
import ChainTelemetry from "@/components/ChainTelemetry";

export default function IDE() {
  const { user } = useAuth();
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [tree, setTree] = useState([]);
  const [tabs, setTabs] = useState([]); // [{path, content, language, dirty, score}]
  const [activeTab, setActiveTab] = useState(null);
  const [leftView, setLeftView] = useState("files"); // files | git | gauntlet
  const [bottomTab, setBottomTab] = useState("terminal"); // terminal | problems
  const [previewOpen, setPreviewOpen] = useState(false);
  const [inlineOpen, setInlineOpen] = useState(false);
  const [hardBlock, setHardBlock] = useState(null); // { matches, intent, onConfirm(token) }
  const [gauntletStatus, setGauntletStatus] = useState({ score: 5, issues: 0 });
  const [isMobile, setIsMobile] = useState(typeof window !== "undefined" && window.innerWidth < 900);
  // mobile drawer: null | "left" | "right" | "bottom"
  const [mobileDrawer, setMobileDrawer] = useState(null);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 900);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const editorRef = useRef(null);
  const telemetryRef = useRef(null);

  // Load projects on mount
  useEffect(() => {
    (async () => {
      let ps = await listProjects();
      if (!ps.length) {
        const p = await createProject("first-shard");
        ps = [p];
      }
      setProjects(ps);
      setActiveProject(ps[0]);
    })();
  }, []);

  // Load tree when project changes (auto-open README only once per project)
  const autoOpenedFor = useRef(null);
  useEffect(() => {
    if (!activeProject) return;
    (async () => {
      const r = await projectTree(activeProject.project_id);
      setTree(r.tree);
      if (autoOpenedFor.current !== activeProject.project_id) {
        autoOpenedFor.current = activeProject.project_id;
        const readme = r.tree.find((f) => f.type === "file" && f.name.toLowerCase() === "readme.md");
        if (readme) openFile(readme.path);
      }
    })();
    // eslint-disable-next-line
  }, [activeProject]);

  const openFile = useCallback(async (path) => {
    if (!activeProject) return;
    // Optimistic dedupe to survive StrictMode double-invoke
    let alreadyOpen = false;
    setTabs((prev) => {
      if (prev.some((t) => t.path === path)) { alreadyOpen = true; return prev; }
      return prev;
    });
    setActiveTab(path);
    if (alreadyOpen) return;
    const f = await readFile(activeProject.project_id, path);
    setTabs((prev) => {
      if (prev.some((t) => t.path === path)) return prev;
      return [...prev, { path, content: f.content, language: f.language, dirty: false, score: null }];
    });
  }, [activeProject]);

  const closeTab = (path) => {
    setTabs((prev) => prev.filter((t) => t.path !== path));
    if (activeTab === path) {
      const remain = tabs.filter((t) => t.path !== path);
      setActiveTab(remain.length ? remain[remain.length - 1].path : null);
    }
  };

  const updateTabContent = (path, content) => {
    setTabs((prev) =>
      prev.map((t) => (t.path === path ? { ...t, content, dirty: true } : t))
    );
  };

  const saveActive = useCallback(async () => {
    const tab = tabs.find((t) => t.path === activeTab);
    if (!tab || !activeProject) return;
    await writeFile(activeProject.project_id, tab.path, tab.content);
    setTabs((prev) => prev.map((t) => (t.path === tab.path ? { ...t, dirty: false } : t)));
  }, [tabs, activeTab, activeProject]);

  const refreshTree = useCallback(async () => {
    if (!activeProject) return;
    const r = await projectTree(activeProject.project_id);
    setTree(r.tree);
  }, [activeProject]);

  const setActiveTabScore = (score, issues) => {
    setTabs((prev) => prev.map((t) => (t.path === activeTab ? { ...t, score } : t)));
    setGauntletStatus({ score: score?.score ?? 5, issues: issues ?? 0 });
  };

  // Keyboard: Cmd/Ctrl+S save, Cmd/Ctrl+K inline edit
  useEffect(() => {
    const h = (e) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveActive();
      } else if (meta && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (activeTab) setInlineOpen(true);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [activeTab, saveActive]);

  const activeTabObj = tabs.find((t) => t.path === activeTab);

  return (
    <div className="h-screen w-screen flex flex-col bg-midnight text-gridwhite overflow-hidden">
      <TopBar
        user={user}
        projects={projects}
        activeProject={activeProject}
        onProjectChange={setActiveProject}
        onNewProject={async (name) => {
          const p = await createProject(name);
          setProjects((prev) => [...prev, p]);
          setActiveProject(p);
        }}
        gauntletStatus={gauntletStatus}
        previewOpen={previewOpen}
        onTogglePreview={() => setPreviewOpen((v) => !v)}
      />

      <div className="flex-1 flex min-h-0 relative">
        {!isMobile && <LeftRail active={leftView} onChange={setLeftView} />}

        {/* Left panel: files / git / gauntlet snapshot. On mobile: drawer overlay */}
        <div
          className={
            isMobile
              ? `fixed inset-y-12 left-0 z-30 w-72 border-r border-cyan/10 bg-midnight flex flex-col transform transition-transform duration-200 ease-out ${
                  mobileDrawer === "left" ? "translate-x-0" : "-translate-x-full"
                }`
              : "w-64 border-r border-cyan/10 bg-midnight/80 flex flex-col"
          }
        >
          {isMobile && (
            <div className="flex border-b border-cyan/10">
              {["files", "git", "gauntlet"].map((k) => (
                <button
                  key={k}
                  onClick={() => setLeftView(k)}
                  className={`flex-1 py-2 font-display text-[0.65rem] tracking-[0.2em] ${
                    leftView === k ? "text-cyan border-b border-cyan" : "text-alloy"
                  }`}
                  data-testid={`mobile-left-${k}`}
                >{k.toUpperCase()}</button>
              ))}
            </div>
          )}
          {leftView === "files" && (
            <FileTree
              tree={tree}
              onOpen={(p) => { openFile(p); if (isMobile) setMobileDrawer(null); }}
              onRefresh={refreshTree}
              activePath={activeTab}
              projectId={activeProject?.project_id}
            />
          )}
          {leftView === "git" && activeProject && (
            <GitHubPanel
              projectId={activeProject.project_id}
              onRefresh={refreshTree}
              onProjectCloned={(p) => {
                setProjects((prev) => [...prev, p]);
                setActiveProject(p);
              }}
            />
          )}
          {leftView === "gauntlet" && (
            <div className="p-4 text-sm text-alloy">
              <div className="font-display text-cyan tracking-widest text-xs mb-3">GAUNTLET SUMMARY</div>
              <div className="font-mono text-xs">
                Current file score:{" "}
                <span className="text-cyan">{activeTabObj?.score?.score ?? "-"} / 5</span>
              </div>
              <div className="mt-1 font-mono text-xs">
                Issues: <span className="text-orange">{activeTabObj?.score?.issues?.length ?? 0}</span>
              </div>
              <div className="mt-4 text-[0.7rem] leading-relaxed">
                Open a file and hit the <span className="text-cyan">GAUNTLET</span> tab to run the
                Five Masters review (Claude Sonnet 4.5).
              </div>
            </div>
          )}
        </div>

        {/* Center: editor + bottom panel */}
        <div className="flex-1 flex flex-col min-w-0">
          <EditorPane
            tabs={tabs}
            activeTab={activeTab}
            onSelectTab={setActiveTab}
            onCloseTab={closeTab}
            onChange={updateTabContent}
            onSave={saveActive}
            editorRef={editorRef}
            onCmdK={() => setInlineOpen(true)}
          />

          {/* Bottom (terminal/problems) — hidden on mobile by default, accessed via drawer */}
          {(!isMobile || mobileDrawer === "bottom") && (
            <div
              className={
                isMobile
                  ? "fixed inset-x-0 bottom-12 top-1/2 z-30 border-t border-cyan/10 flex flex-col bg-midnight shadow-2xl"
                  : "h-64 border-t border-cyan/10 flex flex-col bg-midnight/60"
              }
            >
              <div className="flex items-center border-b border-cyan/10">
                <button
                  data-testid="bottom-tab-terminal"
                  onClick={() => setBottomTab("terminal")}
                  className={`px-4 py-2 font-display text-[0.7rem] tracking-[0.25em] ${
                    bottomTab === "terminal" ? "text-cyan border-b-2 border-cyan" : "text-alloy"
                  }`}
                >TERMINAL</button>
                <button
                  data-testid="bottom-tab-problems"
                  onClick={() => setBottomTab("problems")}
                  className={`px-4 py-2 font-display text-[0.7rem] tracking-[0.25em] ${
                    bottomTab === "problems" ? "text-cyan border-b-2 border-cyan" : "text-alloy"
                  }`}
                >
                  PROBLEMS <span className="ml-2 font-mono text-orange">{activeTabObj?.score?.issues?.length ?? 0}</span>
                </button>
                {isMobile && (
                  <button
                    onClick={() => setMobileDrawer(null)}
                    className="ml-auto px-3 py-2 text-alloy hover:text-orange font-display text-[0.7rem]"
                    data-testid="mobile-close-bottom"
                  >CLOSE</button>
                )}
              </div>
              <div className="flex-1 min-h-0">
                {bottomTab === "terminal" && activeProject && (
                  <TerminalPane projectId={activeProject.project_id} onHardBlock={setHardBlock} />
                )}
                {bottomTab === "problems" && (
                  <ProblemsPanel
                    issues={activeTabObj?.score?.issues || []}
                    language={activeTabObj?.language}
                  />
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: AI coworker. On mobile: drawer from right */}
        <div
          className={
            isMobile
              ? `fixed inset-y-12 right-0 z-30 w-screen max-w-md border-l border-cyan/10 bg-midnight flex flex-col transform transition-transform duration-200 ease-out ${
                  mobileDrawer === "right" ? "translate-x-0" : "translate-x-full"
                }`
              : "w-[26rem] border-l border-cyan/10 bg-midnight/80 flex flex-col min-w-0"
          }
        >
          <AICoworker
            project={activeProject}
            activeTab={activeTabObj}
            tree={tree}
            onScoreUpdate={setActiveTabScore}
            onApplyRefined={(code) => updateTabContent(activeTab, code)}
            onAICall={() => telemetryRef.current?.refresh()}
          />
        </div>

        {/* Drawer scrim on mobile */}
        {isMobile && mobileDrawer && (
          <div
            onClick={() => setMobileDrawer(null)}
            className="fixed inset-0 z-20 bg-midnight/60 backdrop-blur-sm"
            data-testid="mobile-scrim"
          />
        )}

        {/* Slide-in preview */}
        {previewOpen && activeProject && (
          <LivePreview
            projectId={activeProject.project_id}
            onClose={() => setPreviewOpen(false)}
            backendUrl={process.env.REACT_APP_BACKEND_URL}
          />
        )}
      </div>

      <ChainTelemetry ref={telemetryRef} />

      {/* Mobile bottom dock */}
      {isMobile && (
        <div className="h-12 border-t border-cyan/15 bg-midnight flex items-stretch z-30" data-testid="mobile-dock">
          <DockButton label="FILES" active={mobileDrawer === "left"} onClick={() => setMobileDrawer(mobileDrawer === "left" ? null : "left")} testid="dock-files" />
          <DockButton label="TERM" active={mobileDrawer === "bottom"} onClick={() => setMobileDrawer(mobileDrawer === "bottom" ? null : "bottom")} testid="dock-terminal" />
          <DockButton label="J" active={mobileDrawer === "right"} onClick={() => setMobileDrawer(mobileDrawer === "right" ? null : "right")} testid="dock-ai" />
        </div>
      )}

      {inlineOpen && activeTabObj && (
        <InlineEditModal
          tab={activeTabObj}
          onClose={() => setInlineOpen(false)}
          onApply={(code) => {
            updateTabContent(activeTab, code);
            setInlineOpen(false);
          }}
        />
      )}

      {hardBlock && (
        <HardBlockModal
          matches={hardBlock.matches}
          intent={hardBlock.intent}
          onCancel={() => setHardBlock(null)}
          onConfirm={(token) => {
            const cb = hardBlock.onConfirm;
            setHardBlock(null);
            cb(token);
          }}
        />
      )}
    </div>
  );
}

function DockButton({ label, active, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className={`flex-1 flex items-center justify-center font-display text-[0.65rem] tracking-[0.25em] border-r border-cyan/10 last:border-r-0 ${
        active ? "text-cyan bg-steel border-t-2 border-t-cyan" : "text-alloy"
      }`}
    >{label}</button>
  );
}
