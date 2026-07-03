import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { getStoredToken } from "@/lib/api";

export default function TerminalPane({ projectId }) {
  const hostRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const wsRef = useRef(null);
  const [status, setStatus] = useState("connecting");

  useEffect(() => {
    if (!hostRef.current) return;
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "JetBrains Mono, ui-monospace, Menlo, monospace",
      fontSize: 12,
      scrollback: 5000,
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
    termRef.current = term;
    fitRef.current = fit;

    // Forward raw input bytes (arrow keys, ctrl-c, tab, everything) to the
    // backend PTY. xterm.js gives us the proper escape sequences already.
    const dataSub = term.onData((data) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    function sendResize() {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "resize",
          cols: term.cols,
          rows: term.rows,
        }));
      }
    }

    const ro = new ResizeObserver(() => {
      try { fit.fit(); sendResize(); } catch { /* ignore */ }
    });
    ro.observe(hostRef.current);

    return () => {
      ro.disconnect();
      dataSub.dispose();
      const ws = wsRef.current;
      if (ws) try { ws.close(); } catch { /* ignore */ }
      term.dispose();
    };
  }, []);

  // (Re)connect WS whenever the active project changes
  useEffect(() => {
    if (!termRef.current || !projectId) return;
    const term = termRef.current;
    const fit = fitRef.current;

    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
    }
    term.write("\x1b[36m// connecting to interactive shell…\x1b[0m\r\n");
    setStatus("connecting");

    const httpUrl = process.env.REACT_APP_BACKEND_URL || "";
    const wsBase = httpUrl.replace(/^https?:\/\//, (m) =>
      m === "https://" ? "wss://" : "ws://");
    const token = getStoredToken();
    const tokenQ = token ? `&token=${encodeURIComponent(token)}` : "";
    const url = `${wsBase}/api/terminal/ws?project_id=${encodeURIComponent(projectId)}${tokenQ}`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      try {
        ws.send(JSON.stringify({
          type: "resize", cols: term.cols, rows: term.rows,
        }));
      } catch { /* ignore */ }
    };
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data));
      } else if (typeof ev.data === "string") {
        try {
          const obj = JSON.parse(ev.data);
          if (obj && obj.type === "error") {
            term.write(`\r\n\x1b[31m// shell error: ${obj.msg}\x1b[0m\r\n`);
            return;
          }
        } catch { /* not JSON — write as text */ }
        term.write(ev.data);
      }
    };
    ws.onclose = (ev) => {
      setStatus("closed");
      if (ev.code === 4401) {
        term.write("\r\n\x1b[31m// shell session unauthorized — refresh & sign in again.\x1b[0m\r\n");
      } else {
        term.write("\r\n\x1b[33m// shell disconnected. Click RECONNECT to spawn a new session.\x1b[0m\r\n");
      }
    };
    ws.onerror = () => { setStatus("error"); };

    // Re-fit on connect
    try { fit?.fit(); } catch { /* ignore */ }
  }, [projectId]);

  function reconnect() {
    const term = termRef.current;
    if (!term) return;
    term.clear();
    // trigger the project-change effect by forcing a no-op state ping
    if (wsRef.current) try { wsRef.current.close(); } catch { /* ignore */ }
    const httpUrl = process.env.REACT_APP_BACKEND_URL || "";
    const wsBase = httpUrl.replace(/^https?:\/\//, (m) =>
      m === "https://" ? "wss://" : "ws://");
    const token = getStoredToken();
    const tokenQ = token ? `&token=${encodeURIComponent(token)}` : "";
    const url = `${wsBase}/api/terminal/ws?project_id=${encodeURIComponent(projectId)}${tokenQ}`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    setStatus("connecting");
    ws.onopen = () => {
      setStatus("connected");
      try { ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })); }
      catch { /* ignore */ }
    };
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) term.write(new Uint8Array(ev.data));
      else if (typeof ev.data === "string") term.write(ev.data);
    };
    ws.onclose = () => { setStatus("closed"); };
    ws.onerror = () => { setStatus("error"); };
  }

  const statusColor = status === "connected" ? "var(--viridian)"
    : status === "connecting" ? "var(--cyan)"
      : "var(--orange)";

  return (
    <div className="h-full w-full bg-midnight flex flex-col" data-testid="terminal-pane">
      <div className="h-6 border-b border-cyan/10 flex items-center px-3 gap-2 text-[0.65rem] font-mono">
        <span className="w-2 h-2 inline-block" style={{ background: statusColor }} />
        <span className="text-alloy" data-testid="terminal-status">
          shell · {status}
        </span>
        <span className="text-alloy/50">// type `j-help` for command reference</span>
        {status !== "connected" && (
          <button
            onClick={reconnect}
            className="ml-auto text-cyan hover:underline"
            data-testid="terminal-reconnect"
          >reconnect</button>
        )}
      </div>
      <div ref={hostRef} className="flex-1 w-full" />
    </div>
  );
}
