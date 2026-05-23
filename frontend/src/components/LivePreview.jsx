import { useEffect, useState } from "react";
import { X, ArrowsClockwise, DeviceMobile, Desktop } from "@phosphor-icons/react";
import { readFile } from "@/lib/api";

export default function LivePreview({ projectId, onClose, backendUrl }) {
  const [html, setHtml] = useState("");
  const [device, setDevice] = useState("desktop");

  async function refresh() {
    try {
      const f = await readFile(projectId, "index.html");
      setHtml(f.content);
    } catch {
      setHtml(
        `<html><body style="background:#050709;color:#7D8597;font-family:'JetBrains Mono',monospace;display:flex;align-items:center;justify-content:center;height:100vh"><div>// no index.html found in project root</div></body></html>`
      );
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [projectId]);

  const width = device === "mobile" ? 390 : "100%";

  return (
    <div className="fixed inset-y-0 right-0 w-[640px] z-40 bg-midnight border-l border-cyan/20 flex flex-col shadow-2xl" data-testid="live-preview">
      <div className="h-10 border-b border-cyan/15 flex items-center px-3 gap-2">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">LIVE PREVIEW</div>
        <div className="ml-2 font-mono text-[0.65rem] text-alloy">// index.html</div>
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
      <div className="flex-1 bg-steel flex items-center justify-center">
        <iframe
          title="Live Preview"
          srcDoc={html}
          style={{ width, height: "100%", border: 0, background: "#fff" }}
          sandbox="allow-scripts"
          data-testid="preview-iframe"
        />
      </div>
    </div>
  );
}
