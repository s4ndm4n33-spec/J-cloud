import { useEffect, useRef, useState } from "react";

/**
 * Boot-time Matrix-style code-rain animation in Sovereign Shards cyan.
 *
 * Renders a fullscreen canvas of falling glyphs with the brand mark
 * + status line in the foreground. Auto-dismisses after `durationMs`
 * (or when the user clicks/hits any key).
 *
 * Glyph palette: katakana half-width (the iconic Matrix set) + hex
 * digits + a sprinkling of Sovereign Shards motif characters
 * (#, /, >, ·, █, ▒, ▓).
 */
const GLYPHS =
  "0123456789ABCDEF" +
  "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン" +
  "#/>·█▒▓░<{[]}";

const BOOT_LINES = [
  "[ OK ]  loading sovereign substrate",
  "[ OK ]  attaching five masters AST core",
  "[ OK ]  spinning J chat / refine / governance chains",
  "[ OK ]  mounting workspace bus + chronicle ledger",
  "[ OK ]  arming destructive interlock (override-only)",
  "[ OK ]  PTY shells reserved (5 / user)",
  "[ OK ]  J persona online — sardonic wit module engaged",
  "[ >>>>] hand-off to operator",
];

export default function LaunchSequence({ durationMs = 2600, onDone }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const [fadeOut, setFadeOut] = useState(false);
  const [linesShown, setLinesShown] = useState(0);

  // Stagger the boot lines so they print like a real boot log
  useEffect(() => {
    const interval = Math.max(80, Math.floor(durationMs / (BOOT_LINES.length + 2)));
    const timers = [];
    BOOT_LINES.forEach((_, i) => {
      timers.push(setTimeout(() => setLinesShown((n) => Math.max(n, i + 1)), interval * (i + 1)));
    });
    return () => timers.forEach(clearTimeout);
  }, [durationMs]);

  // Schedule dismissal
  useEffect(() => {
    const fadeAt = setTimeout(() => setFadeOut(true), durationMs);
    const exitAt = setTimeout(() => onDone?.(), durationMs + 450);
    return () => { clearTimeout(fadeAt); clearTimeout(exitAt); };
  }, [durationMs, onDone]);

  // Skip on user input
  useEffect(() => {
    const skip = () => { setFadeOut(true); setTimeout(() => onDone?.(), 250); };
    const t = setTimeout(() => {
      window.addEventListener("keydown", skip, { once: true });
      window.addEventListener("click", skip, { once: true });
    }, 150); // small grace period so accidental clicks don't kill it instantly
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", skip);
      window.removeEventListener("click", skip);
    };
  }, [onDone]);

  // The actual code rain
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let cols = 0;
    let drops = [];
    let fontSize = 16;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(window.innerWidth * dpr);
      canvas.height = Math.floor(window.innerHeight * dpr);
      canvas.style.width = window.innerWidth + "px";
      canvas.style.height = window.innerHeight + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      fontSize = window.innerWidth < 720 ? 14 : 16;
      cols = Math.ceil(window.innerWidth / fontSize);
      drops = new Array(cols).fill(0).map(() => Math.random() * -50);
      ctx.font = `${fontSize}px "JetBrains Mono", monospace`;
    }
    resize();
    window.addEventListener("resize", resize);

    function frame() {
      // Trailing fade
      ctx.fillStyle = "rgba(5, 7, 9, 0.08)";
      ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

      for (let i = 0; i < cols; i++) {
        const x = i * fontSize;
        const y = drops[i] * fontSize;
        const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];

        // Lead glyph: bright cyan with bloom
        if (Math.random() < 0.985) {
          ctx.fillStyle = "rgba(125, 133, 151, 0.55)"; // alloy, dim trail
        }
        ctx.fillText(ch, x, y);

        // Bright head
        ctx.fillStyle = "rgba(0, 217, 255, 0.95)";
        ctx.fillText(ch, x, y);

        // Reset drop randomly (creates the cascading streams effect)
        if (y > window.innerHeight && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i] += 1;
      }
      rafRef.current = requestAnimationFrame(frame);
    }
    rafRef.current = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <div
      data-testid="launch-sequence"
      className={`fixed inset-0 z-[100] bg-midnight transition-opacity duration-[450ms] ease-out ${
        fadeOut ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
    >
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block" />

      {/* HUD corner brackets */}
      <div className="absolute inset-6 border border-cyan/15 pointer-events-none">
        <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan" />
        <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan" />
        <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-cyan" />
        <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-cyan" />
      </div>

      {/* Centered identity card */}
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <div className="font-display tracking-[0.5em] text-cyan text-[0.6rem] sm:text-[0.7rem] mb-2 animate-pulse">
          // INTEGRITY VERIFIED
        </div>
        <div className="font-display font-extrabold text-3xl sm:text-5xl md:text-6xl text-gridwhite tracking-tight">
          SOVEREIGN <span className="text-cyan">SHARDS</span>
        </div>
        <div className="font-mono text-[0.7rem] sm:text-[0.8rem] text-alloy tracking-[0.3em] mt-2">
          DETERMINISTIC <span className="text-cyan">·</span> AUTONOMOUS <span className="text-cyan">·</span> SUBSTRATE
        </div>

        {/* Boot log */}
        <div className="mt-8 sm:mt-10 w-[min(92vw,640px)] font-mono text-[0.7rem] sm:text-[0.75rem] text-alloy leading-relaxed">
          {BOOT_LINES.slice(0, linesShown).map((ln, i) => (
            <div key={i} className="flex items-baseline gap-2 opacity-0 animate-[fadein_220ms_forwards]">
              <span className="text-cyan/80">{ln.startsWith("[ OK ]") ? "[ OK ]" : "[ >>>>]"}</span>
              <span>{ln.replace(/^\[[^\]]+\]\s+/, "")}</span>
            </div>
          ))}
        </div>

        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 font-mono text-[0.6rem] sm:text-[0.65rem] text-alloy/70 tracking-[0.3em]">
          // press any key to skip
        </div>
      </div>

      <style>{`
        @keyframes fadein { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: none; } }
      `}</style>
    </div>
  );
}
