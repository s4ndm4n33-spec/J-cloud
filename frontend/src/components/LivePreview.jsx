import { useEffect, useState, useMemo } from "react";
import { X, ArrowsClockwise, DeviceMobile, Desktop, CaretDown } from "@phosphor-icons/react";
import { readFile } from "@/lib/api";

/**
 * Live Preview slide-in panel.
 *
 * Renders ANY HTML file from the project. Selection priority:
 *   1. `initialPath` (e.g., the currently active editor tab if it's HTML)
 *   2. `index.html` if present
 *   3. First .html file found in the tree
 *
 * A dropdown in the header lets the user switch between every .html file
 * the tree contains. Re-opens / refreshes pick up edits via Save.
 */
export default function LivePreview({ projectId, onClose, htmlFiles = [], initialPath }) {
  const [device, setDevice] = useState("desktop");
  const [html, setHtml] = useState("");
  const [openDropdown, setOpenDropdown] = useState(false);
  const [error, setError] = useState(null);

  // Resolve the file we should show
  const fileList = useMemo(() => {
    // De-dupe + sort, with index.html bubbled to top
    const set = new Set(htmlFiles);
    const arr = Array.from(set).sort((a, b) => {
      if (a.toLowerCase() === "index.html") return -1;
      if (b.toLowerCase() === "index.html") return 1;
      return a.localeCompare(b);
    });
    return arr;
  }, [htmlFiles]);

  const [selectedPath, setSelectedPath] = useState(() => {
    if (initialPath && /\.html?$/i.test(initialPath)) return initialPath;
    if (fileList.includes("index.html")) return "index.html";
    return fileList[0] || "index.html";
  });

  // Sync selection if initialPath changes while panel stays open (eg. user opened another HTML in editor)
  useEffect(() => {
    if (initialPath && /\.html?$/i.test(initialPath) && initialPath !== selectedPath) {
      setSelectedPath(initialPath);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPath]);

  async function refresh() {
    setError(null);
    try {
      const f = await readFile(projectId, selectedPath);
      setHtml(f.content);
    } catch (e) {
      setError(e?.response?.data?.detail || `Could not read ${selectedPath}`);
      setHtml("");
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [projectId, selectedPath]);

  const width = device === "mobile" ? 390 : "100%";
  const hasOptions = fileList.length > 0;

  return (
    <div className="fixed inset-y-0 right-0 w-[640px] z-40 bg-midnight border-l border-cyan/20 flex flex-col shadow-2xl" data-testid="live-preview">
      <div className="h-10 border-b border-cyan/15 flex items-center px-3 gap-2 relative">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">LIVE PREVIEW</div>

        {/* HTML file selector */}
        <div className="relative">
          <button
            data-testid="preview-file-select"
            onClick={() => setOpenDropdown((v) => !v)}
            disabled={!hasOptions}
            className="flex items-center gap-1 px-2 py-1 font-mono text-[0.7rem] text-alloy hover:text-cyan border border-cyan/15 hover:border-cyan/40 transition-colors disabled:opacity-40"
            title="Choose which HTML file to preview"
          >
            <span className="text-cyan/80">//</span>
            <span className="max-w-[200px] truncate">{selectedPath || "(no html)"}</span>
            <CaretDown size={10} className={openDropdown ? "rotate-180 transition-transform" : "transition-transform"} />
          </button>
          {openDropdown && hasOptions && (
            <div
              className="absolute left-0 top-full mt-1 z-50 min-w-[260px] max-h-72 overflow-auto bg-midnight border border-cyan/30 shadow-[0_8px_24px_rgba(0,217,255,0.15)] py-1"
              data-testid="preview-file-dropdown"
            >
              {fileList.map((p) => (
                <button
                  key={p}
                  onClick={() => { setSelectedPath(p); setOpenDropdown(false); }}
                  data-testid={`preview-file-option-${p}`}
                  className={`w-full text-left px-3 py-1.5 font-mono text-[0.7rem] truncate ${
                    p === selectedPath ? "text-cyan bg-cyan/10" : "text-gridwhite/80 hover:bg-cyan/5 hover:text-cyan"
                  }`}
                >{p}</button>
              ))}
            </div>
          )}
        </div>

        <div className="ml-auto flex items-center gap-1">
          <button data-testid="preview-desktop" onClick={() => setDevice("desktop")} className={device === "desktop" ? "text-cyan" : "text-alloy hover:text-cyan"}>
            <Desktop size={14} />
          </button>
          <button data-testid="preview-mobile" onClick={() => setDevice("mobile")} className={device === "mobile" ? "text-cyan" : "text-alloy hover:text-cyan"}>
            <DeviceMobile size={14} />
          </button>
          <button data-testid="preview-refresh" onClick={refresh} className="text-alloy hover:text-cyan">
            <ArrowsClockwise size={14} />
          </button>
          <button data-testid="preview-close" onClick={onClose} className="text-alloy hover:text-orange ml-2">
            <X size={14} weight="bold" />
          </button>
        </div>
      </div>

      <div className="flex-1 bg-steel flex items-center justify-center relative">
        {error ? (
          <div className="font-mono text-xs text-orange p-4 text-center" data-testid="preview-error">
            // {error}
          </div>
        ) : !hasOptions ? (
          <div className="font-mono text-xs text-alloy p-4 text-center">
            // no HTML files in this project — create one in the tree
          </div>
        ) : (
          <iframe
            title="Live Preview"
            srcDoc={html}
            style={{ width, height: "100%", border: 0, background: "#fff" }}
            sandbox="allow-scripts"
            data-testid="preview-iframe"
          />
        )}
      </div>
    </div>
  );
}
