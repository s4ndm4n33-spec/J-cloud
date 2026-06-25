import { useState, useMemo, useRef } from "react";
import { File, Folder, FolderOpen, ArrowsClockwise, CaretDown, CaretRight, Upload, DownloadSimple, Archive, FolderPlus, Trash } from "@phosphor-icons/react";
import { uploadFile, uploadZip, uploadFolder, downloadUrl, downloadProjectZip, deleteFile } from "@/lib/api";

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
  const folderInputRef = useRef(null);
  const [uploading, setUploading] = useState(null); // { kind, name, pct }
  const [dragOver, setDragOver] = useState(false);

  const rows = useMemo(() => flatten(tree, openMap), [tree, openMap]);

  function toggle(path) {
    setOpenMap((prev) => ({ ...prev, [path]: !(prev[path] ?? true) }));
  }

  async function ingestFiles(files, basePathArr) {
    if (!files.length || !projectId) return;
    setUploading({ kind: "files", name: `${files.length} file(s)`, pct: 0 });
    try {
      // If any file is a .zip, prefer zip extraction; else folder upload preserving paths
      const zips = files.filter((f) => /\.zip$/i.test(f.name));
      const others = files.filter((f) => !/\.zip$/i.test(f.name));
      for (const z of zips) {
        setUploading({ kind: "zip", name: z.name, pct: 0 });
        await uploadZip(projectId, z, {}, (e) => {
          if (e.total) setUploading({ kind: "zip", name: z.name, pct: Math.round((e.loaded / e.total) * 100) });
        });
      }
      if (others.length) {
        setUploading({ kind: "folder", name: `${others.length} file(s)`, pct: 0 });
        // Use webkitRelativePath when available
        const paths = others.map((f, i) => f.webkitRelativePath || (basePathArr?.[i] ?? f.name));
        await uploadFolder(projectId, others, paths, (e) => {
          if (e.total) setUploading({ kind: "folder", name: `${others.length} file(s)`, pct: Math.round((e.loaded / e.total) * 100) });
        });
      }
    } catch (e) {
      console.error("upload failed", e);
    } finally {
      setUploading(null);
      onRefresh?.();
    }
  }

  async function handleUpload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    await ingestFiles(files);
  }

  async function handleFolderUpload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    await ingestFiles(files);
  }

  function onDragOver(e) { e.preventDefault(); setDragOver(true); }
  function onDragLeave() { setDragOver(false); }
  async function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const items = e.dataTransfer.items;
    const collected = [];
    const paths = [];
    if (items && items.length && items[0].webkitGetAsEntry) {
      // Walk directories recursively
      const walkers = [];
      for (const item of items) {
        const entry = item.webkitGetAsEntry?.();
        if (entry) walkers.push(walkEntry(entry, "", collected, paths));
      }
      await Promise.all(walkers);
    } else {
      for (const f of Array.from(e.dataTransfer.files)) { collected.push(f); paths.push(f.name); }
    }
    await ingestFiles(collected, paths);
  }

  function handleDownload(path) {
    window.open(downloadUrl(projectId, path), "_blank");
  }
  async function handleDownloadZip(folderPath = "") {
    if (!projectId) return;
    try {
      await downloadProjectZip(projectId, folderPath);
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Download failed");
    }
  }
  async function handleDelete(path) {
    if (!projectId) return;
    if (!window.confirm(`Delete "${path}"? This cannot be undone.`)) return;
    try {
      await deleteFile(projectId, path);
      onRefresh?.();
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Delete failed");
    }
  }

  return (
    <div
      className="flex flex-col h-full relative"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10 gap-1">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">FILES</div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Upload files (zip auto-extracts)"
            className="text-alloy hover:text-cyan"
            data-testid="tree-upload"
          ><Upload size={12} /></button>
          <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleUpload} data-testid="tree-upload-input" />
          <button
            onClick={() => folderInputRef.current?.click()}
            title="Upload folder"
            className="text-alloy hover:text-cyan"
            data-testid="tree-upload-folder"
          ><FolderPlus size={12} /></button>
          <input
            ref={folderInputRef}
            type="file"
            webkitdirectory=""
            directory=""
            multiple
            className="hidden"
            onChange={handleFolderUpload}
            data-testid="tree-upload-folder-input"
          />
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

      {uploading && (
        <div className="px-3 py-1.5 border-b border-cyan/10 bg-steel/60" data-testid="upload-progress">
          <div className="font-mono text-[0.65rem] text-cyan flex items-center justify-between">
            <span>// {uploading.kind === "zip" ? "extracting" : "uploading"} {uploading.name}</span>
            <span>{uploading.pct}%</span>
          </div>
          <div className="h-1 bg-midnight mt-1 overflow-hidden">
            <div className="h-full bg-cyan transition-all duration-150" style={{ width: `${uploading.pct}%` }} />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto scrollbar-thin py-1" data-testid="file-tree">
        {rows.map((row) => {
          const isActive = row.type === "file" && row.path === activePath;
          if (row.type === "dir") {
            return (
              <div
                key={`d:${row.path}`}
                className="group flex items-center hover:bg-cyan/5"
                style={{ paddingLeft: 6 + row.depth * 12 }}
              >
                <button
                  data-testid={`tree-dir-${row.path}`}
                  onClick={() => toggle(row.path)}
                  className="flex-1 flex items-center gap-1 py-1 text-left text-[0.78rem] text-gridwhite/90"
                >
                  {row.isOpen ? <CaretDown size={10} /> : <CaretRight size={10} />}
                  {row.isOpen ? <FolderOpen size={14} className="text-cyan" /> : <Folder size={14} className="text-alloy" />}
                  <span className="font-mono">{row.name}</span>
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDownloadZip(row.path); }}
                  title={`Download "${row.name}" as zip`}
                  className="text-alloy hover:text-cyan px-1.5 opacity-0 group-hover:opacity-100"
                  data-testid={`tree-download-dir-${row.path}`}
                ><Archive size={10} /></button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(row.path); }}
                  title={`Delete "${row.name}"`}
                  className="text-alloy hover:text-orange px-1.5 opacity-0 group-hover:opacity-100"
                  data-testid={`tree-delete-dir-${row.path}`}
                ><Trash size={10} /></button>
              </div>
            );
          }
          return (
            <div
              key={`f:${row.path}`}
              className={`group flex items-center hover:bg-cyan/5 ${isActive ? "bg-cyan/10" : ""}`}
              style={{ paddingLeft: 6 + row.depth * 12 + 12 }}
            >
              <button
                data-testid={`tree-file-${row.path}`}
                onClick={() => onOpen(row.path)}
                className={`flex-1 flex items-center gap-2 py-1 text-left text-[0.78rem] ${isActive ? "text-cyan" : "text-gridwhite/80"}`}
              >
                <File size={12} className={isActive ? "text-cyan" : "text-alloy"} />
                <span className="font-mono truncate">{row.name}</span>
              </button>
              <button
                onClick={() => handleDownload(row.path)}
                title="Download"
                className="text-alloy hover:text-cyan px-1.5 opacity-0 group-hover:opacity-100"
                data-testid={`tree-download-${row.path}`}
              ><DownloadSimple size={10} /></button>
              <button
                onClick={() => handleDelete(row.path)}
                title="Delete"
                className="text-alloy hover:text-orange px-1.5 opacity-0 group-hover:opacity-100"
                data-testid={`tree-delete-${row.path}`}
              ><Trash size={10} /></button>
            </div>
          );
        })}
        {!rows.length && (
          <div className="px-3 py-4 text-alloy font-mono text-xs">// empty — drop files here</div>
        )}
      </div>

      {dragOver && (
        <div className="absolute inset-0 z-20 border-2 border-dashed border-cyan bg-cyan/10 flex items-center justify-center pointer-events-none" data-testid="drop-zone">
          <div className="font-display text-cyan tracking-[0.25em] text-sm">DROP TO INGEST</div>
        </div>
      )}
    </div>
  );
}

function walkEntry(entry, prefix, files, paths) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        files.push(file);
        paths.push(prefix + file.name);
        resolve();
      }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      function readBatch() {
        reader.readEntries((batch) => {
          if (!batch.length) { resolve(Promise.all(all)); return; }
          for (const e of batch) all.push(walkEntry(e, prefix + entry.name + "/", files, paths));
          readBatch();
        }, () => resolve());
      }
      readBatch();
    } else { resolve(); }
  });
}
