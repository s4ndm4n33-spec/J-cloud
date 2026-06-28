import { useState, useMemo, useRef, forwardRef } from "react";
import {
  File, Folder, FolderOpen, ArrowsClockwise, CaretDown, CaretRight,
  Upload, DownloadSimple, Archive, FolderPlus, Trash, PencilSimple,
  FilePlus, Copy, Eye,
} from "@phosphor-icons/react";
import {
  uploadZip, uploadFolder, downloadUrl, downloadProjectZip,
  deleteFile, renameFile, mkdir, writeFile,
} from "@/lib/api";
import ContextMenu from "@/components/ContextMenu";

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

function dirnameOf(path) {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}
function basenameOf(path) {
  const i = path.lastIndexOf("/");
  return i < 0 ? path : path.slice(i + 1);
}

export default function FileTree({ tree, onOpen, onRefresh, activePath, projectId, onRenamed, onPreviewHtml }) {
  const [openMap, setOpenMap] = useState({});
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const [uploading, setUploading] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  // Context menu state: { x, y, row } where row = {type, path, name}
  const [menu, setMenu] = useState(null);
  // Inline rename state: { path, value, isDir }
  const [renaming, setRenaming] = useState(null);
  const renameInputRef = useRef(null);

  const rows = useMemo(() => flatten(tree, openMap), [tree, openMap]);

  function toggle(path) {
    setOpenMap((prev) => ({ ...prev, [path]: !(prev[path] ?? true) }));
  }

  async function ingestFiles(files, basePathArr) {
    if (!files.length || !projectId) return;
    setUploading({ kind: "files", name: `${files.length} file(s)`, pct: 0 });
    try {
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

  // ---------- Rename (inline) ----------

  function beginRename(row) {
    setRenaming({ path: row.path, value: row.name, isDir: row.type === "dir" });
    // Focus on the next tick (after input renders)
    setTimeout(() => {
      const el = renameInputRef.current;
      if (el) {
        el.focus();
        // Select stem only (before extension) for files; full name for dirs
        const name = row.name;
        const dot = !row.type || row.type === "dir" ? -1 : name.lastIndexOf(".");
        if (dot > 0) el.setSelectionRange(0, dot);
        else el.select();
      }
    }, 0);
  }

  async function commitRename() {
    const r = renaming;
    if (!r) return;
    const trimmed = (r.value || "").trim();
    if (!trimmed || trimmed === basenameOf(r.path) || /[/\\]/.test(trimmed)) {
      setRenaming(null);
      return;
    }
    const newPath = (dirnameOf(r.path) ? dirnameOf(r.path) + "/" : "") + trimmed;
    try {
      await renameFile(projectId, r.path, newPath);
      setRenaming(null);
      onRenamed?.(r.path, newPath, r.isDir);
      onRefresh?.();
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Rename failed");
      setRenaming(null);
    }
  }

  // ---------- Create new file / folder ----------

  async function handleNewFile(parentPath = "") {
    const name = window.prompt(
      parentPath ? `New file inside "${parentPath}":` : "New file name:", "untitled.txt",
    );
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed || /[/\\]/.test(trimmed)) {
      window.alert("Name cannot contain slashes.");
      return;
    }
    const newPath = (parentPath ? parentPath + "/" : "") + trimmed;
    try {
      await writeFile(projectId, newPath, "");
      onRefresh?.();
      onOpen?.(newPath);
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Create failed");
    }
  }

  async function handleNewFolder(parentPath = "") {
    const name = window.prompt(
      parentPath ? `New folder inside "${parentPath}":` : "New folder name:", "new-folder",
    );
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed || /[/\\]/.test(trimmed)) {
      window.alert("Name cannot contain slashes.");
      return;
    }
    const newPath = (parentPath ? parentPath + "/" : "") + trimmed;
    try {
      await mkdir(projectId, newPath);
      setOpenMap((p) => ({ ...p, [parentPath]: true, [newPath]: true }));
      onRefresh?.();
    } catch (e) {
      window.alert(e?.response?.data?.detail || "Create folder failed");
    }
  }

  function copyPath(path) {
    try {
      navigator.clipboard?.writeText(path);
    } catch { /* ignore */ }
  }

  // ---------- Build context menu items for a row ----------

  function menuItemsFor(row) {
    const isDir = row.type === "dir";
    const parent = isDir ? row.path : dirnameOf(row.path);
    const isHtml = !isDir && /\.html?$/i.test(row.name);
    const items = [
      isDir
        ? { label: "Open / Toggle", icon: <FolderOpen size={12} />, onClick: () => toggle(row.path) }
        : { label: "Open file", icon: <File size={12} />, onClick: () => onOpen?.(row.path) },
    ];
    if (isHtml && onPreviewHtml) {
      items.push({
        label: "Open in preview", icon: <Eye size={12} />,
        onClick: () => onPreviewHtml(row.path),
      });
    }
    items.push(
      { divider: true },
      { label: "New file…", icon: <FilePlus size={12} />, onClick: () => handleNewFile(parent) },
      { label: "New folder…", icon: <FolderPlus size={12} />, onClick: () => handleNewFolder(parent) },
      { divider: true },
      { label: "Rename", icon: <PencilSimple size={12} />, shortcut: "F2", onClick: () => beginRename(row) },
      { label: "Copy path", icon: <Copy size={12} />, onClick: () => copyPath(row.path) },
      isDir
        ? { label: "Download as zip", icon: <Archive size={12} />, onClick: () => handleDownloadZip(row.path) }
        : { label: "Download", icon: <DownloadSimple size={12} />, onClick: () => handleDownload(row.path) },
      { divider: true },
      { label: isDir ? "Delete folder" : "Delete file", icon: <Trash size={12} />,
        danger: true, onClick: () => handleDelete(row.path) },
    );
    return items;
  }

  function onRowContextMenu(e, row) {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, row });
  }

  function onEmptyContextMenu(e) {
    e.preventDefault();
    setMenu({
      x: e.clientX, y: e.clientY,
      row: { type: "dir", path: "", name: "(root)" },
    });
  }

  return (
    <div
      className="flex flex-col h-full relative"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onContextMenu={onEmptyContextMenu}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10 gap-1">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">FILES</div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => handleNewFile("")}
            title="New file"
            className="text-alloy hover:text-cyan"
            data-testid="tree-new-file"
          ><FilePlus size={12} /></button>
          <button
            onClick={() => handleNewFolder("")}
            title="New folder"
            className="text-alloy hover:text-cyan"
            data-testid="tree-new-folder"
          ><FolderPlus size={12} /></button>
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
          ><Folder size={12} /></button>
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
            onClick={() => handleDownloadZip()}
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
          const isRenaming = renaming?.path === row.path;

          if (row.type === "dir") {
            return (
              <div
                key={`d:${row.path}`}
                className="group flex items-center hover:bg-cyan/5"
                style={{ paddingLeft: 6 + row.depth * 12 }}
                onContextMenu={(e) => onRowContextMenu(e, row)}
              >
                {isRenaming ? (
                  <div className="flex-1 flex items-center gap-1 py-1 text-[0.78rem] text-cyan">
                    <CaretDown size={10} />
                    <FolderOpen size={14} className="text-cyan" />
                    <RenameInput
                      ref={renameInputRef}
                      value={renaming.value}
                      onChange={(v) => setRenaming({ ...renaming, value: v })}
                      onCommit={commitRename}
                      onCancel={() => setRenaming(null)}
                    />
                  </div>
                ) : (
                  <button
                    data-testid={`tree-dir-${row.path}`}
                    onClick={() => toggle(row.path)}
                    onDoubleClick={(e) => { e.preventDefault(); beginRename(row); }}
                    className="flex-1 flex items-center gap-1 py-1 text-left text-[0.78rem] text-gridwhite/90"
                  >
                    {row.isOpen ? <CaretDown size={10} /> : <CaretRight size={10} />}
                    {row.isOpen ? <FolderOpen size={14} className="text-cyan" /> : <Folder size={14} className="text-alloy" />}
                    <span className="font-mono">{row.name}</span>
                  </button>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); beginRename(row); }}
                  title={`Rename "${row.name}"`}
                  className="text-alloy hover:text-cyan px-1.5 opacity-0 group-hover:opacity-100"
                  data-testid={`tree-rename-dir-${row.path}`}
                ><PencilSimple size={10} /></button>
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
              onContextMenu={(e) => onRowContextMenu(e, row)}
            >
              {isRenaming ? (
                <div className="flex-1 flex items-center gap-2 py-1 text-[0.78rem] text-cyan">
                  <File size={12} className="text-cyan" />
                  <RenameInput
                    ref={renameInputRef}
                    value={renaming.value}
                    onChange={(v) => setRenaming({ ...renaming, value: v })}
                    onCommit={commitRename}
                    onCancel={() => setRenaming(null)}
                  />
                </div>
              ) : (
                <button
                  data-testid={`tree-file-${row.path}`}
                  onClick={() => onOpen(row.path)}
                  onDoubleClick={(e) => { e.preventDefault(); beginRename(row); }}
                  className={`flex-1 flex items-center gap-2 py-1 text-left text-[0.78rem] ${isActive ? "text-cyan" : "text-gridwhite/80"}`}
                >
                  <File size={12} className={isActive ? "text-cyan" : "text-alloy"} />
                  <span className="font-mono truncate">{row.name}</span>
                </button>
              )}
              <button
                onClick={() => beginRename(row)}
                title="Rename"
                className="text-alloy hover:text-cyan px-1.5 opacity-0 group-hover:opacity-100"
                data-testid={`tree-rename-${row.path}`}
              ><PencilSimple size={10} /></button>
              {/\.html?$/i.test(row.name) && onPreviewHtml && (
                <button
                  onClick={() => onPreviewHtml(row.path)}
                  title="Open in Live Preview"
                  className="text-alloy hover:text-cyan px-1.5 opacity-0 group-hover:opacity-100"
                  data-testid={`tree-preview-${row.path}`}
                ><Eye size={10} /></button>
              )}
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
          <div className="px-3 py-4 text-alloy font-mono text-xs">// empty — right-click or drop files here</div>
        )}
      </div>

      {dragOver && (
        <div className="absolute inset-0 z-20 border-2 border-dashed border-cyan bg-cyan/10 flex items-center justify-center pointer-events-none" data-testid="drop-zone">
          <div className="font-display text-cyan tracking-[0.25em] text-sm">DROP TO INGEST</div>
        </div>
      )}

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={
            menu.row.path === ""
              ? [
                  { label: "New file…", icon: <FilePlus size={12} />, onClick: () => handleNewFile("") },
                  { label: "New folder…", icon: <FolderPlus size={12} />, onClick: () => handleNewFolder("") },
                  { divider: true },
                  { label: "Upload files…", icon: <Upload size={12} />, onClick: () => fileInputRef.current?.click() },
                  { label: "Refresh tree", icon: <ArrowsClockwise size={12} />, onClick: () => onRefresh?.() },
                ]
              : menuItemsFor(menu.row)
          }
          testid="file-context-menu"
        />
      )}
    </div>
  );
}

// Inline rename input — handles Enter / Escape / blur
const RenameInput = forwardRef(function RenameInput(
  { value, onChange, onCommit, onCancel }, ref,
) {
  return (
    <input
      ref={ref}
      type="text"
      value={value}
      data-testid="tree-rename-input"
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); onCommit(); }
        else if (e.key === "Escape") { e.preventDefault(); onCancel(); }
      }}
      onBlur={onCommit}
      className="flex-1 bg-midnight border border-cyan/60 px-1 py-0 font-mono text-[0.78rem] text-cyan focus:outline-none focus:border-cyan"
    />
  );
});

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
