import Editor from "@monaco-editor/react";
import { X, FloppyDisk, Sparkle } from "@phosphor-icons/react";

export default function EditorPane({
  tabs, activeTab, onSelectTab, onCloseTab, onChange, onSave, editorRef, onCmdK,
}) {
  const active = tabs.find((t) => t.path === activeTab);

  function handleMount(editor, monaco) {
    editorRef.current = { editor, monaco };
    // Define Sovereign theme
    monaco.editor.defineTheme("sovereign", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "comment", foreground: "7D8597", fontStyle: "italic" },
        { token: "string", foreground: "1F8F6B" },
        { token: "keyword", foreground: "00D9FF" },
        { token: "number", foreground: "FF6A1A" },
        { token: "type", foreground: "E7ECF5" },
        { token: "function", foreground: "00D9FF" },
      ],
      colors: {
        "editor.background": "#050709",
        "editor.foreground": "#E7ECF5",
        "editorLineNumber.foreground": "#7D8597",
        "editorLineNumber.activeForeground": "#00D9FF",
        "editorCursor.foreground": "#00D9FF",
        "editor.selectionBackground": "#00D9FF35",
        "editor.lineHighlightBackground": "#0B0F14",
        "editorIndentGuide.background": "#0B0F14",
        "editorIndentGuide.activeBackground": "#00D9FF40",
      },
    });
    monaco.editor.setTheme("sovereign");
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyK, () => onCmdK());
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSave());
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Tab bar */}
      <div className="h-9 bg-midnight border-b border-cyan/10 flex items-stretch overflow-x-auto scrollbar-thin">
        {tabs.map((t) => {
          const isActive = t.path === activeTab;
          const score = t.score?.score;
          return (
            <div
              key={t.path}
              data-testid={`tab-${t.path}`}
              onClick={() => onSelectTab(t.path)}
              className={`flex items-center gap-2 pl-3 pr-2 py-1 border-r border-cyan/10 cursor-pointer min-w-[8rem] ${
                isActive ? "bg-steel text-cyan border-b border-b-cyan" : "text-alloy hover:text-gridwhite"
              }`}
            >
              <span className="font-mono text-xs truncate">{t.path.split("/").pop()}</span>
              {t.dirty && <span className="h-1.5 w-1.5 rounded-full bg-orange"></span>}
              {score !== undefined && score !== null && (
                <span
                  className="font-mono text-[0.6rem] px-1"
                  style={{ color: score >= 4 ? "var(--viridian)" : score >= 2 ? "var(--orange)" : "#FF2D55" }}
                >
                  {score}/5
                </span>
              )}
              <button
                data-testid={`tab-close-${t.path}`}
                onClick={(e) => { e.stopPropagation(); onCloseTab(t.path); }}
                className="text-alloy hover:text-orange ml-1"
              >
                <X size={10} weight="bold" />
              </button>
            </div>
          );
        })}
        <div className="ml-auto flex items-center gap-2 px-3">
          <button data-testid="cmd-k" onClick={onCmdK} className="btn-ghost text-[0.65rem] py-1 px-2" disabled={!active}>
            <Sparkle size={12} /> CMD+K
          </button>
          <button data-testid="save-button" onClick={onSave} className="btn-ghost text-[0.65rem] py-1 px-2" disabled={!active}>
            <FloppyDisk size={12} /> SAVE
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 bg-midnight" data-testid="monaco-host">
        {active ? (
          <Editor
            height="100%"
            theme="sovereign"
            language={active.language}
            value={active.content}
            onChange={(v) => onChange(active.path, v ?? "")}
            onMount={handleMount}
            options={{
              fontFamily: "JetBrains Mono",
              fontSize: 13,
              minimap: { enabled: false },
              smoothScrolling: true,
              cursorBlinking: "smooth",
              fontLigatures: true,
              padding: { top: 12 },
              renderLineHighlight: "all",
              scrollBeyondLastLine: false,
            }}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-alloy gap-3 font-mono">
            <div className="font-display text-cyan tracking-[0.3em] text-sm">SOVEREIGN SHARDS · J</div>
            <div className="text-xs">// open a file to begin</div>
            <div className="text-[0.65rem] text-alloy/60">cmd+k inline refine · cmd+s save</div>
          </div>
        )}
      </div>
    </div>
  );
}
