import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { execCommand } from "@/lib/api";

export default function TerminalPane({ projectId, onHardBlock }) {
  const hostRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const bufRef = useRef("");
  const pendingRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!hostRef.current) return;
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "JetBrains Mono",
      fontSize: 12,
      theme: {
        background: "#050709",
        foreground: "#E7ECF5",
        cursor: "#00D9FF",
        selectionBackground: "#00D9FF35",
        black: "#0B0F14",
        cyan: "#00D9FF",
        green: "#1F8F6B",
        yellow: "#FF6A1A",
        red: "#FF2D55",
      },
      allowTransparency: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    term.write("\x1b[36m// J@sovereign \x1b[37m~/shard\x1b[0m\r\n");
    writePrompt(term);
    termRef.current = term;
    fitRef.current = fit;
    setReady(true);

    term.onData((data) => onData(data));

    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* ignore */ }
    });
    ro.observe(hostRef.current);

    return () => {
      ro.disconnect();
      term.dispose();
    };
    // eslint-disable-next-line
  }, []);

  function writePrompt(term) {
    term.write("\x1b[36m> \x1b[0m");
  }

  async function runCommand(cmd, overrideToken = null) {
    const term = termRef.current;
    if (!cmd.trim()) { writePrompt(term); return; }
    const r = await execCommand(projectId, cmd, overrideToken);
    if (r.status === 423 && r.blocked) {
      term.write(`\r\n\x1b[33m[INTEGRITY HALT] destructive pattern detected:\x1b[0m\r\n`);
      r.matches.forEach((m) => {
        term.write(`  \x1b[31m✗\x1b[0m ${m.pattern} — ${m.reason}\r\n`);
      });
      term.write(`\x1b[33m// password override required\x1b[0m\r\n`);
      pendingRef.current = cmd;
      onHardBlock({
        matches: r.matches,
        intent: cmd,
        onConfirm: async (token) => {
          term.write(`\x1b[32m[OVERRIDE GRANTED]\x1b[0m\r\n`);
          await runCommand(cmd, token);
        },
      });
      return;
    }
    if (r.stdout) term.write(r.stdout.replace(/\n/g, "\r\n"));
    if (r.stderr) term.write(`\x1b[31m${r.stderr.replace(/\n/g, "\r\n")}\x1b[0m`);
    if (r.exit_code !== 0) term.write(`\r\n\x1b[33m[exit ${r.exit_code}]\x1b[0m`);
    term.write("\r\n");
    writePrompt(term);
  }

  function onData(data) {
    const term = termRef.current;
    for (const ch of data) {
      const code = ch.charCodeAt(0);
      if (code === 13) { // Enter
        term.write("\r\n");
        const cmd = bufRef.current;
        bufRef.current = "";
        runCommand(cmd);
      } else if (code === 127) { // Backspace
        if (bufRef.current.length > 0) {
          bufRef.current = bufRef.current.slice(0, -1);
          term.write("\b \b");
        }
      } else if (code >= 32) {
        bufRef.current += ch;
        term.write(ch);
      }
    }
  }

  return (
    <div className="h-full w-full bg-midnight" data-testid="terminal-pane">
      <div ref={hostRef} className="h-full w-full" />
      {!ready && (
        <div className="font-mono text-xs text-alloy p-3">// initializing terminal…</div>
      )}
    </div>
  );
}
