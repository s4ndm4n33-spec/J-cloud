import { useState, useMemo, useRef } from "react";
import { File, Folder, FolderOpen, ArrowsClockwise, CaretDown, CaretRight, Upload, DownloadSimple, Archive } from "@phosphor-icons/react";
import { uploadFile, downloadUrl, downloadZipUrl } from "@/lib/api";

function flatten(tree, openMap, depth = 0, out = []) {
  for (const n of tree) {
    if (n.type === "dir") {
      const isOpen = openMap[n.path] ?? depth < 1;
      out.push({ ...n, depth, isOpen });
      if (isOpen && n.children) flatten(n.children, openMap, depth + 1, out);
    } else {
      out.push({ ...n, depth });
    }
  }
  return out;
}

export default function FileTree({ tree, onOpen, onRefresh, activePath, projectId }) {
  const [openMap, setOpenMap] = useState({});
  const fileInputRef = useRef(null);

  const rows = useMemo(() => flatten(tree, openMap), [tree, openMap]);

  function toggle(path) {
    setOpenMap((prev) => ({ ...prev, [path]: !(prev[path] ?? true) }));
  }

  async function handleUpload(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length || !projectId) return;
    for (const f of files) {
      await uploadFile(projectId, f, f.name);
    }
    e.target.value = "";
    onRefresh?.();
  }

  function handleDownload(path) {
    window.open(downloadUrl(projectId, path), "_blank");
  }

  function handleDownloadZip() {
    if (!projectId) return;
    window.open(downloadZipUrl(projectId), "_blank");
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10 gap-1">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">FILES</div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Upload file(s)"
            className="text-alloy hover:text-cyan"
            data-testid="tree-upload"
          ><Upload size={12} /></button>
          <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleUpload} data-testid="tree-upload-input" />
          <button
            onClick={handleDownloadZip}
            title="Download project zip"
            className="text-alloy hover:text-cyan"
            data-testid="tree-download-zip"
          ><Archive size={12} /></button>
          <button onClick={onRefresh} data-testid="tree-refresh" className="text-alloy hover:text-cyan">
            <ArrowsClockwise size={12} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto scrollbar-thin py-1" data-testid="file-tree">
        {rows.map((row) => {
          const isActive = row.type === "file" && row.path === activePath;
          if (row.type === "dir") {
            return (
              <button
                key={`d:${row.path}`}
                data-testid={`tree-dir-${row.path}`}
                onClick={() => toggle(row.path)}
                className="w-full flex items-center gap-1 px-2 py-1 hover:bg-cyan/5 text-left text-[0.78rem] text-gridwhite/90"
                style={{ paddingLeft: 6 + row.depth * 12 }}
              >
                {row.isOpen
                  ? <CaretDown size={10} />
                  : <CaretRight size={10} />}
                {row.isOpen
                  ? <FolderOpen size={14} className="text-cyan" />
                  : <Folder size={14} className="text-alloy" />}
                <span className="font-mono">{row.name}</span>
              </button>
            );
          }
          return (
            <div
              key={`f:${row.path}`}
              className={`group flex items-center hover:bg-cyan/5 ${
                isActive ? "bg-cyan/10" : ""
              }`}
              style={{ paddingLeft: 6 + row.depth * 12 + 12 }}
            >
              <button
                data-testid={`tree-file-${row.path}`}
                onClick={() => onOpen(row.path)}
                className={`flex-1 flex items-center gap-2 py-1 text-left text-[0.78rem] ${
                  isActive ? "text-cyan" : "text-gridwhite/80"
                }`}
              >
                <File size={12} className={isActive ? "text-cyan" : "text-alloy"} />
                <span className="font-mono truncate">{row.name}</span>
              </button>
              <button
                onClick={() => handleDownload(row.path)}
                title="Download"
                className="text-alloy hover:text-cyan px-2 opacity-0 group-hover:opacity-100"
                data-testid={`tree-download-${row.path}`}
              ><DownloadSimple size={10} /></button>
            </div>
          );
        })}
        {!rows.length && (
          <div className="px-3 py-4 text-alloy font-mono text-xs">// empty</div>
        )}
      </div>
    </div>
  );
}
