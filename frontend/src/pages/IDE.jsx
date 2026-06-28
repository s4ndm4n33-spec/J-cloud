import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels";
import { useAuth } from "@/context/AuthContext";
import {
  listProjects, createProject, projectTree, readFile, writeFile,
  getTutorialState,
} from "@/lib/api";
import TopBar from "@/components/TopBar";
import LeftRail from "@/components/LeftRail";
import FileTree from "@/components/FileTree";
import EditorPane from "@/components/EditorPane";
import AICoworker from "@/components/AICoworker";
import TerminalPane from "@/components/TerminalPane";
import ProblemsPanel from "@/components/ProblemsPanel";
import GitHubPanel from "@/components/GitHubPanel";
import GlossaryPanel from "@/components/GlossaryPanel";
import LivePreview from "@/components/LivePreview";
import InlineEditModal from "@/components/InlineEditModal";
import HardBlockModal from "@/components/HardBlockModal";
import ChainTelemetry from "@/components/ChainTelemetry";
import Tutorial from "@/components/Tutorial";
import LaunchSequence from "@/components/LaunchSequence";

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
  const [terminalHeight, setTerminalHeight] = useState(() => {
    const saved = parseInt(localStorage.getItem("gauntlet-terminal-height") || "260", 10);
    return Number.isFinite(saved) && saved >= 80 ? saved : 260;
  });
  // mobile drawer: null | "left" | "right" | "bottom"
  const [mobileDrawer, setMobileDrawer] = useState(null);
  // tutorial: null = not checked yet, false = dismissed/done, true = show
  const [tutorialOpen, setTutorialOpen] = useState(false);
  // Launch sequence: shown once after auth (set by AuthCallback via sessionStorage)
  // OR when replayed from the TopBar.
  const [launchOpen, setLaunchOpen] = useState(() => {
    try {
      if (sessionStorage.getItem("gauntlet_play_launch") === "1") {
        sessionStorage.removeItem("gauntlet_play_launch");
        return true;
      }
    } catch { /* ignore */ }
    return false;
  });

  useEffect(() => {
    (async () => {
      try {
        const r = await getTutorialState();
        if (!r.completed) setTutorialOpen(true);
      } catch { /* ignore */ }
    })();
  }, []);

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

  // Collect every .html file from the tree (recursive flatten) for the Live Preview selector
  const htmlFiles = useMemo(() => {
    const out = [];
    const walk = (nodes) => {
      for (const n of nodes) {
        if (n.type === "dir" && n.children) walk(n.children);
        else if (n.type === "file" && /\.html?$/i.test(n.name)) out.push(n.path);
      }
    };
    walk(tree);
    return out;
  }, [tree]);

  // The path passed to LivePreview when it opens: the active tab if it's HTML,
  // explicit override via `previewPath`, else null (preview decides default).
  const [previewPath, setPreviewPath] = useState(null);
  const initialPreviewPath = previewPath
    || (activeTabObj && /\.html?$/i.test(activeTabObj.path) ? activeTabObj.path : null);

  // Opening preview via right-click "Open in Preview": set explicit path + open.
  const openPreviewWithPath = useCallback((path) => {
    setPreviewPath(path);
    setPreviewOpen(true);
  }, []);


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
        onOpenTutorial={() => setTutorialOpen(true)}
        onProjectDeleted={(deletedId) => {
          setProjects((prev) => {
            const next = prev.filter((p) => p.project_id !== deletedId);
            // If we just deleted the active project, switch to the first remaining one
            if (activeProject?.project_id === deletedId) {
              setActiveProject(next[0] || null);
              setTabs([]);
              setActiveTab(null);
            }
            return next;
          });
        }}
      />

      {(() => {
        const leftPanelBody = (
          <>
            {isMobile && (
              <div className="flex border-b border-cyan/10">
                {["files", "git", "gauntlet", "glossary"].map((k) => (
                  <button
                    key={k}
                    onClick={() => setLeftView(k)}
                    className={`flex-1 py-2 font-display text-[0.6rem] tracking-[0.2em] ${
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
                onPreviewHtml={(p) => { openPreviewWithPath(p); if (isMobile) setMobileDrawer(null); }}
                onRenamed={(oldPath, newPath, isDir) => {
                  // Update any open tabs whose paths match (or are inside a renamed folder)
                  setTabs((prev) => prev.map((t) => {
                    if (t.path === oldPath) return { ...t, path: newPath };
                    if (isDir && t.path.startsWith(oldPath + "/")) {
                      return { ...t, path: newPath + t.path.slice(oldPath.length) };
                    }
                    return t;
                  }));
                  setActiveTab((cur) => {
                    if (cur === oldPath) return newPath;
                    if (isDir && cur && cur.startsWith(oldPath + "/")) {
                      return newPath + cur.slice(oldPath.length);
                    }
                    return cur;
                  });
                }}
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
            {leftView === "glossary" && <GlossaryPanel />}
          </>
        );

        const bottomPanelBody = (
          <>
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
              {!isMobile && (
                <span className="ml-auto pr-3 font-mono text-[0.6rem] text-alloy/60">
                  // drag the divider to resize
                </span>
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
          </>
        );

        const editorBody = (
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
        );

        const aiPanelBody = (
          <AICoworker
            project={activeProject}
            activeTab={activeTabObj}
            tree={tree}
            onScoreUpdate={setActiveTabScore}
            onApplyRefined={(code) => updateTabContent(activeTab, code)}
            onAICall={() => telemetryRef.current?.refresh()}
          />
        );

        if (isMobile) {
          return (
            <div className="flex-1 flex min-h-0 relative">
              <div
                className={`fixed inset-y-12 left-0 z-30 w-72 border-r border-cyan/10 bg-midnight flex flex-col transform transition-transform duration-200 ease-out ${
                  mobileDrawer === "left" ? "translate-x-0" : "-translate-x-full"
                }`}
              >{leftPanelBody}</div>

              <div className="flex-1 flex flex-col min-w-0">
                {editorBody}
                {mobileDrawer === "bottom" && (
                  <div className="fixed inset-x-0 bottom-12 top-1/2 z-30 border-t border-cyan/10 flex flex-col bg-midnight shadow-2xl">
                    {bottomPanelBody}
                  </div>
                )}
              </div>

              <div
                className={`fixed inset-y-12 right-0 z-30 w-screen max-w-md border-l border-cyan/10 bg-midnight flex flex-col transform transition-transform duration-200 ease-out ${
                  mobileDrawer === "right" ? "translate-x-0" : "translate-x-full"
                }`}
              >{aiPanelBody}</div>

              {mobileDrawer && (
                <div
                  onClick={() => setMobileDrawer(null)}
                  className="fixed inset-0 z-20 bg-midnight/60 backdrop-blur-sm"
                  data-testid="mobile-scrim"
                />
              )}

              {previewOpen && activeProject && (
                <LivePreview
                  projectId={activeProject.project_id}
                  onClose={() => { setPreviewOpen(false); setPreviewPath(null); }}
                  htmlFiles={htmlFiles}
                  initialPath={initialPreviewPath}
                />
              )}
            </div>
          );
        }

        // Desktop: full resizable layout. v4 quirks:
        //   - Numeric size = px; strings = percent
        //   - Don't add flex/flex-col to Panels — the library handles layout
        //   - id prop becomes data-testid automatically
        return (
          <div className="flex-1 flex min-h-0 relative">
            <LeftRail active={leftView} onChange={setLeftView} />
            <PanelGroup direction="horizontal" id="gauntlet-h" className="flex-1">
              <Panel defaultSize="18" minSize="10" maxSize="45" id="panel-left"
                     className="border-r border-cyan/10 bg-midnight/80">
                <div className="h-full flex flex-col">{leftPanelBody}</div>
              </Panel>
              <PanelResizeHandle id="resize-handle-left"
                className="w-1 bg-cyan/10 hover:bg-cyan/40 transition-colors cursor-col-resize" />
              <Panel defaultSize="56" minSize="25" id="panel-center" className="min-w-0">
                <div className="h-full flex flex-col">
                  <div className="flex-1 min-h-0 flex flex-col">
                    {editorBody}
                  </div>
                  <div
                    data-testid="resize-handle-bottom"
                    role="separator"
                    aria-orientation="horizontal"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      const startY = e.clientY;
                      const startH = terminalHeight;
                      const onMove = (ev) => {
                        const delta = startY - ev.clientY;
                        const next = Math.max(80, Math.min(900, startH + delta));
                        setTerminalHeight(next);
                      };
                      const onUp = () => {
                        document.removeEventListener("mousemove", onMove);
                        document.removeEventListener("mouseup", onUp);
                        try {
                          localStorage.setItem("gauntlet-terminal-height",
                            String(terminalHeight));
                        } catch { /* ignore */ }
                      };
                      document.addEventListener("mousemove", onMove);
                      document.addEventListener("mouseup", onUp);
                    }}
                    className="h-1.5 bg-cyan/10 hover:bg-cyan/50 cursor-row-resize flex-shrink-0 relative group"
                  >
                    <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 flex justify-center pointer-events-none">
                      <div className="h-0.5 w-12 bg-cyan/40 group-hover:bg-cyan rounded-full" />
                    </div>
                  </div>
                  <div
                    className="border-t border-cyan/10 bg-midnight/60 flex-shrink-0 flex flex-col"
                    style={{ height: terminalHeight }}
                  >
                    {bottomPanelBody}
                  </div>
                </div>
              </Panel>
              <PanelResizeHandle id="resize-handle-right"
                className="w-1 bg-cyan/10 hover:bg-cyan/40 transition-colors cursor-col-resize" />
              <Panel defaultSize="26" minSize="15" maxSize="55" id="panel-right"
                     className="border-l border-cyan/10 bg-midnight/80 min-w-0">
                <div className="h-full flex flex-col">{aiPanelBody}</div>
              </Panel>
            </PanelGroup>

            {previewOpen && activeProject && (
              <LivePreview
                projectId={activeProject.project_id}
                onClose={() => { setPreviewOpen(false); setPreviewPath(null); }}
                htmlFiles={htmlFiles}
                initialPath={initialPreviewPath}
              />
            )}
          </div>
        );
      })()}

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

      {tutorialOpen && <Tutorial onClose={() => setTutorialOpen(false)} />}

      {launchOpen && <LaunchSequence onDone={() => setLaunchOpen(false)} />}
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
