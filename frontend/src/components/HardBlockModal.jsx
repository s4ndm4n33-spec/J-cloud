import { useState } from "react";
import { WarningOctagon, X } from "@phosphor-icons/react";
import { requestOverride } from "@/lib/api";

export default function HardBlockModal({ matches, intent, onConfirm, onCancel }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function attempt() {
    setBusy(true); setError("");
    try {
      const r = await requestOverride(password, intent);
      onConfirm(r.override_token);
    } catch (e) {
      setError(e?.response?.data?.detail || "Override rejected.");
    } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-midnight/85 backdrop-blur-sm" data-testid="hard-block-modal">
      <div className="w-full max-w-2xl panel relative p-6"
        style={{ border: "2px solid var(--orange)", background: "rgba(5,7,9,0.95)" }}>
        <button onClick={onCancel} className="absolute top-3 right-3 text-alloy hover:text-orange" data-testid="hard-block-cancel">
          <X size={14} weight="bold" />
        </button>
        <div className="flex items-center gap-3">
          <WarningOctagon size={28} weight="fill" className="text-orange" />
          <div>
            <div className="font-display text-2xl font-extrabold tracking-tight text-orange">INTEGRITY HALT</div>
            <div className="font-mono text-[0.65rem] tracking-[0.2em] text-alloy mt-0.5">
              // VERIFICATION REQUIRED · destructive operation detected
            </div>
          </div>
        </div>

        <div className="mt-4 font-mono text-xs text-gridwhite/90 leading-relaxed">
          J refuses to execute the requested operation without an authenticated override. Sovereign
          policy: <span className="text-cyan">if it can't prove integrity, it halts.</span>
        </div>

        <div className="mt-3 p-2 bg-steel/80 border border-orange/30">
          <div className="font-mono text-[0.65rem] text-alloy mb-1">// INTENT</div>
          <div className="font-mono text-[0.75rem] text-orange break-all">{intent}</div>
        </div>

        <div className="mt-3 space-y-1">
          <div className="font-mono text-[0.65rem] text-alloy">// MATCHES</div>
          {matches.map((m, i) => (
            <div key={i} className="font-mono text-[0.7rem]">
              <span className="text-orange">{m.pattern}</span>{" "}
              <span className="text-alloy">— {m.reason}</span>
            </div>
          ))}
        </div>

        <div className="mt-5">
          <label className="font-mono text-[0.65rem] tracking-widest text-cyan">OVERRIDE PASSWORD</label>
          <input
            type="password"
            data-testid="override-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") attempt(); }}
            className="w-full mt-1 bg-steel border border-orange/50 px-3 py-2 font-mono text-sm text-orange"
            placeholder="••••••••"
            autoFocus
          />
          {error && <div className="font-mono text-[0.7rem] text-orange mt-1">// {error}</div>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="btn-ghost">ABORT</button>
          <button onClick={attempt} disabled={busy || !password} className="btn-solid btn-danger" data-testid="override-confirm">
            {busy ? "VERIFYING…" : "OVERRIDE"}
          </button>
        </div>
      </div>
    </div>
  );
}
