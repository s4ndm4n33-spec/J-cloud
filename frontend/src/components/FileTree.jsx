import { useState, useMemo } from "react";
import { File, Folder, FolderOpen, ArrowsClockwise, CaretDown, CaretRight } from "@phosphor-icons/react";

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

export default function FileTree({ tree, onOpen, onRefresh, activePath }) {
  const [openMap, setOpenMap] = useState({});

  const rows = useMemo(() => flatten(tree, openMap), [tree, openMap]);

  function toggle(path) {
    setOpenMap((prev) => ({ ...prev, [path]: !(prev[path] ?? true) }));
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-cyan/10">
        <div className="font-display text-cyan tracking-widest text-[0.65rem]">FILES</div>
        <button onClick={onRefresh} data-testid="tree-refresh" className="text-alloy hover:text-cyan">
          <ArrowsClockwise size={12} />
        </button>
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
            <button
              key={`f:${row.path}`}
              data-testid={`tree-file-${row.path}`}
              onClick={() => onOpen(row.path)}
              className={`w-full flex items-center gap-2 px-2 py-1 text-left text-[0.78rem] hover:bg-cyan/5 ${
                isActive ? "bg-cyan/10 text-cyan" : "text-gridwhite/80"
              }`}
              style={{ paddingLeft: 6 + row.depth * 12 + 12 }}
            >
              <File size={12} className={isActive ? "text-cyan" : "text-alloy"} />
              <span className="font-mono truncate flex-1">{row.name}</span>
            </button>
          );
        })}
        {!rows.length && (
          <div className="px-3 py-4 text-alloy font-mono text-xs">// empty</div>
        )}
      </div>
    </div>
  );
}
