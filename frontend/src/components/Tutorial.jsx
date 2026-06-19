import { useEffect, useState, useLayoutEffect } from "react";
import { X, ArrowRight, ArrowLeft, Sparkle } from "@phosphor-icons/react";
import { setTutorialState } from "@/lib/api";

const STEPS = [
  {
    selector: null,
    title: "Welcome, operator.",
    body: "J is awake. Five Masters loaded. This 60-second tour shows you every dial on the rig — file tree, terminal, AI coworker, and the failover key chain. Skip anytime; replay from the ? in the top bar.",
  },
  {
    selector: '[data-testid="top-bar"]',
    title: "Top Bar · mission control.",
    body: "Switch projects, deploy a live preview, open Settings (gear), and replay this tour (?). Your active project name lives here.",
  },
  {
    selector: '[data-testid="project-switcher"]',
    title: "Pick or create a project.",
    body: "Click here to jump between projects or spawn a new one. Each project is its own sandbox with its own file tree, git, and migration log.",
  },
  {
    selector: '[data-testid="file-tree"]',
    title: "File Tree · your workspace.",
    body: "Click a file to open it in a tab. Right-click for new file / new folder / delete. Drop a ZIP here or use the upload button to import an existing codebase.",
  },
  {
    selector: '[data-testid="monaco-host"]',
    title: "Monaco · your editor.",
    body: "Full IntelliSense, multi-tab, syntax highlighting. Highlight code → press ⌘K (Ctrl+K on PC) to ask J for an inline refactor with Five-Masters AST review.",
  },
  {
    selector: '[data-testid="ai-coworker"]',
    title: "J · your AI coworker.",
    body: "Ask anything. J has full project context, can read & write files, run terminal commands, and audit your code. The chain telemetry strip at the bottom shows which model answered.",
  },
  {
    selector: '[data-testid="settings-button"]',
    title: "Settings · keys & failover chain.",
    body: "Three ways to power J: 1) Emergent Universal Key (default, free credits), 2) Your own OpenAI / Anthropic / Gemini keys (BYOK), 3) Your own Ollama / llama.cpp server (private, self-hosted). They auto-failover in that order — no extra config.",
  },
  {
    selector: '[data-testid="private-mode-toggle"]',
    title: "Private Mode · one click.",
    body: "Tap PUBLIC ↔ PRIVATE to lock J to your local server only. Cloud and Universal Key are skipped entirely until you flip back. Requires a linked local server in Settings.",
  },
  {
    selector: null,
    title: "You're armed. Go build.",
    body: "Hard rule: destructive code is blocked until you approve with the override password. Everything you do is logged to migration.log.md (signed). Welcome to the rig.",
  },
];

const PAD = 8;
const TIP_W = 360;
const TIP_H_ESTIMATE = 200;

function getTargetRect(selector) {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  return el.getBoundingClientRect();
}

function clamp(val, min, max) { return Math.max(min, Math.min(val, max)); }

export default function Tutorial({ onClose }) {
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState(null);
  const cur = STEPS[step];

  useLayoutEffect(() => {
    function update() { setRect(getTargetRect(cur.selector)); }
    update();
    const t = setTimeout(update, 50);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [cur.selector, step]);

  async function complete() {
    try { await setTutorialState(true); } catch { /* ignore */ }
    onClose?.();
  }

  // Tooltip positioning
  let tipStyle;
  if (rect) {
    const spaceBelow = window.innerHeight - rect.bottom;
    const placeBelow = spaceBelow > TIP_H_ESTIMATE + 20;
    const top = placeBelow ? rect.bottom + PAD : Math.max(PAD, rect.top - TIP_H_ESTIMATE - PAD);
    let left = rect.left + rect.width / 2 - TIP_W / 2;
    left = clamp(left, PAD, window.innerWidth - TIP_W - PAD);
    tipStyle = { top, left, width: TIP_W };
  } else {
    tipStyle = {
      top: "50%", left: "50%", width: TIP_W,
      transform: "translate(-50%, -50%)",
    };
  }

  // Spotlight cutout: render 4 dark rectangles around the target
  const cutouts = rect ? [
    { left: 0, top: 0, width: "100vw", height: rect.top - PAD },
    { left: 0, top: rect.top - PAD, width: rect.left - PAD, height: rect.height + PAD * 2 },
    { left: rect.right + PAD, top: rect.top - PAD, width: `calc(100vw - ${rect.right + PAD}px)`, height: rect.height + PAD * 2 },
    { left: 0, top: rect.bottom + PAD, width: "100vw", height: `calc(100vh - ${rect.bottom + PAD}px)` },
  ] : null;

  return (
    <div className="fixed inset-0 z-[60] pointer-events-none" data-testid="tutorial-overlay">
      {/* Dim layer */}
      {cutouts ? (
        cutouts.map((c, i) => (
          <div key={i} className="absolute bg-midnight/85 pointer-events-auto" style={c} onClick={complete} />
        ))
      ) : (
        <div className="absolute inset-0 bg-midnight/85 pointer-events-auto" onClick={complete} />
      )}

      {/* Highlight ring */}
      {rect && (
        <div
          className="absolute pointer-events-none border-2 border-cyan animate-pulse"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
            boxShadow: "0 0 24px rgba(0, 220, 255, 0.35)",
          }}
        />
      )}

      {/* Tooltip card */}
      <div
        className="absolute panel tick-corner p-4 pointer-events-auto"
        style={tipStyle}
        data-testid="tutorial-card"
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Sparkle size={12} className="text-cyan" weight="fill" />
            <span className="font-mono text-[0.6rem] tracking-[0.25em] text-cyan">
              TOUR · STEP {step + 1}/{STEPS.length}
            </span>
          </div>
          <button
            onClick={complete}
            className="text-alloy hover:text-orange"
            data-testid="tutorial-skip"
            title="Skip tour"
          ><X size={12} weight="bold" /></button>
        </div>

        <div className="font-display text-[0.95rem] tracking-[0.1em] text-gridwhite mb-1" data-testid="tutorial-title">
          {cur.title}
        </div>
        <div className="font-mono text-[0.7rem] text-alloy leading-relaxed mb-3" data-testid="tutorial-body">
          {cur.body}
        </div>

        {/* Progress bar */}
        <div className="flex gap-1 mb-3">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className="flex-1 h-0.5"
              style={{ background: i <= step ? "var(--cyan)" : "rgba(125,133,151,0.25)" }}
            />
          ))}
        </div>

        <div className="flex items-center justify-between">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="inline-flex items-center gap-1 font-mono text-[0.7rem] text-alloy hover:text-cyan disabled:opacity-40"
            data-testid="tutorial-prev"
          ><ArrowLeft size={12} /> BACK</button>
          <button
            onClick={complete}
            className="font-mono text-[0.65rem] text-alloy hover:text-cyan"
            data-testid="tutorial-skip-bottom"
          >SKIP</button>
          {step < STEPS.length - 1 ? (
            <button
              onClick={() => setStep((s) => s + 1)}
              className="btn-solid text-[0.7rem] inline-flex items-center gap-1.5"
              data-testid="tutorial-next"
            >NEXT <ArrowRight size={12} /></button>
          ) : (
            <button
              onClick={complete}
              className="btn-solid text-[0.7rem]"
              data-testid="tutorial-finish"
            >GO BUILD</button>
          )}
        </div>
      </div>
    </div>
  );
}
