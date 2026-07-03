import { useEffect, useRef } from "react";

/**
 * Lightweight portal-free context menu.
 * Positions itself to stay on-screen and closes on outside click / Escape.
 *
 * props:
 *   x, y         (number)  — viewport coords where the user right-clicked
 *   onClose      (fn)      — invoked on any dismiss
 *   items        (array)   — [{ label, icon, onClick, danger?, divider?, disabled? }]
 *   testid       (string)  — base data-testid; each item gets `${testid}-${index}`
 */
export default function ContextMenu({ x, y, onClose, items, testid = "ctx-menu" }) {
  const ref = useRef(null);

  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    const onEsc = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [onClose]);

  // Clamp to viewport so the menu stays visible
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    if (rect.right > vw) el.style.left = `${vw - rect.width - 8}px`;
    if (rect.bottom > vh) el.style.top = `${vh - rect.height - 8}px`;
  }, []);

  return (
    <div
      ref={ref}
      data-testid={testid}
      role="menu"
      className="fixed z-50 min-w-[180px] py-1 bg-midnight border border-cyan/30 shadow-[0_8px_24px_rgba(0,217,255,0.15)] font-mono text-[0.75rem] text-gridwhite"
      style={{ left: x, top: y }}
    >
      {items.map((it, i) => {
        if (it.divider) {
          return <div key={`d-${i}`} className="my-1 border-t border-cyan/10" />;
        }
        return (
          <button
            key={i}
            data-testid={`${testid}-${i}`}
            disabled={it.disabled}
            onClick={() => { if (!it.disabled) { it.onClick(); onClose(); } }}
            className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
              it.disabled
                ? "text-alloy/40 cursor-not-allowed"
                : it.danger
                  ? "text-orange hover:bg-orange/10"
                  : "text-gridwhite/90 hover:bg-cyan/10 hover:text-cyan"
            }`}
          >
            {it.icon && <span className="flex-shrink-0">{it.icon}</span>}
            <span className="flex-1">{it.label}</span>
            {it.shortcut && (
              <span className="text-alloy/60 text-[0.65rem] tracking-wider">{it.shortcut}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
