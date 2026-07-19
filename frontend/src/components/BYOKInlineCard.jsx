/* Inline BYOK card rendered inside the chat when the backend returns
   401 needs_keys. Three provider chips, paste-and-save, then re-fires
   the user's last message so J actually gets to reply.

   Tone: J is speaking. Sardonic, kind, direct. No dead-ends. */
import { useState } from "react";
import { Key, ArrowRight, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { saveProviderKey, validateProviderKey } from "../lib/api";

const PROVIDERS = [
  {
    id: "openai",
    label: "OpenAI",
    tag: "GPT-5.2 · gpt-5.4-mini",
    url: "https://platform.openai.com/api-keys",
    hint: "starts with sk-",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    tag: "Claude Sonnet 4.5 · Haiku",
    url: "https://console.anthropic.com/settings/keys",
    hint: "starts with sk-ant-",
  },
  {
    id: "gemini",
    label: "Gemini",
    tag: "Gemini 3 Flash · 3.1 Pro",
    url: "https://aistudio.google.com/apikey",
    hint: "starts with AIza",
  },
];

export function BYOKInlineCard({ code, onSaved }) {
  const [picked, setPicked] = useState(null); // provider id
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("SAVING…");
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(null); // { provider, masked }

  const isTavily = code === "needs_tavily_key";

  async function handleSave() {
    if (!picked || !apiKey.trim()) return;
    setBusy(true);
    setErr("");
    // Step 1: live-probe the key against the provider. Fail fast on bad key.
    setBusyLabel("VERIFYING…");
    try {
      const v = await validateProviderKey(picked, apiKey.trim());
      if (!v?.ok) {
        setErr(v?.message || "Key rejected by provider. Check for whitespace or a revoked key.");
        setBusy(false);
        return;
      }
    } catch (e) {
      setErr(
        e?.response?.data?.detail
          || e?.message
          || "Could not reach the provider to verify. Try again.",
      );
      setBusy(false);
      return;
    }
    // Step 2: save it.
    setBusyLabel("SAVING…");
    try {
      const r = await saveProviderKey(picked, apiKey.trim());
      setSaved({ provider: r.provider, masked: r.masked });
      setApiKey("");
      // Fire retry callback after a brief beat so the user sees the OK badge.
      setTimeout(() => onSaved?.(r), 550);
    } catch (e) {
      setErr(
        e?.response?.data?.detail
          || e?.message
          || "Save failed — key looks off. Double-check and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <div
        className="border border-viridian/40 bg-viridian/5 panel p-3 text-sm space-y-1"
        data-testid="byok-inline-saved"
      >
        <div className="flex items-center gap-2 font-mono text-[0.65rem] tracking-widest text-viridian">
          <CheckCircle size={14} weight="fill" />
          <span>{saved.provider.toUpperCase()} KEY SAVED · {saved.masked}</span>
        </div>
        <div className="text-alloy text-[0.75rem]">
          Retrying your last message with your own key…
        </div>
      </div>
    );
  }

  return (
    <div
      className="border border-cyan/30 bg-cyan/[0.03] panel p-3 space-y-3"
      data-testid="byok-inline-card"
    >
      <div className="flex items-start gap-2">
        <Key size={14} weight="fill" className="text-cyan mt-0.5" />
        <div className="text-[0.8rem] leading-relaxed text-gridwhite">
          {isTavily ? (
            <>
              Web search costs money — I&apos;m not going to run yours on someone
              else&apos;s meter. Drop a <span className="text-cyan">Tavily</span> key
              in Settings and I&apos;ll be right back.
            </>
          ) : (
            <>
              Before I burn a token on your behalf, plug in your own key. Pick
              a provider, paste it, save. Encrypted at rest, revocable anytime
              from Settings. Zero surprise bills.
            </>
          )}
        </div>
      </div>

      {isTavily ? (
        <div className="pl-1 pt-1">
          <a
            href="https://tavily.com/#api"
            target="_blank"
            rel="noreferrer"
            className="text-cyan text-[0.75rem] underline underline-offset-2"
          >
            Get a Tavily key →
          </a>
          <div className="text-alloy text-[0.7rem] mt-1">
            Then save it under Settings › Provider Keys (Tavily section — P1,
            coming next). Meanwhile I&apos;ll skip web_search calls.
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5" data-testid="byok-provider-chips">
            {PROVIDERS.map((p) => {
              const active = picked === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => { setPicked(p.id); setErr(""); }}
                  className={`px-2.5 py-1 font-mono text-[0.7rem] tracking-widest border transition-colors ${
                    active
                      ? "border-cyan text-cyan bg-cyan/10"
                      : "border-steel text-alloy hover:border-cyan/60 hover:text-gridwhite"
                  }`}
                  data-testid={`byok-chip-${p.id}`}
                >
                  {p.label.toUpperCase()}
                </button>
              );
            })}
          </div>

          {picked && (
            <div className="space-y-2 pt-1" data-testid="byok-input-row">
              <div className="flex items-center justify-between">
                <div className="font-mono text-[0.65rem] text-alloy">
                  {PROVIDERS.find((p) => p.id === picked).tag}
                </div>
                <a
                  href={PROVIDERS.find((p) => p.id === picked).url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-cyan text-[0.65rem] underline underline-offset-2"
                  data-testid="byok-getkey-link"
                >
                  Get one →
                </a>
              </div>
              <input
                type="password"
                autoFocus
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy && apiKey.trim()) handleSave();
                }}
                placeholder={PROVIDERS.find((p) => p.id === picked).hint}
                className="w-full bg-steel border border-cyan/30 focus:border-cyan px-2 py-1.5 font-mono text-[0.75rem] text-gridwhite outline-none"
                data-testid="byok-key-input"
              />
              <div className="flex items-center justify-between">
                {err ? (
                  <div
                    className="flex items-center gap-1 text-orange text-[0.7rem]"
                    data-testid="byok-error"
                  >
                    <WarningCircle size={11} weight="fill" />
                    <span>{typeof err === "string" ? err : JSON.stringify(err)}</span>
                  </div>
                ) : <span />}
                <button
                  type="button"
                  disabled={!apiKey.trim() || busy}
                  onClick={handleSave}
                  className="flex items-center gap-1.5 px-3 py-1 font-mono text-[0.7rem] tracking-widest border border-cyan text-cyan hover:bg-cyan hover:text-void disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-cyan transition-colors"
                  data-testid="byok-save-btn"
                >
                  {busy ? busyLabel : "SAVE + RETRY"}
                  {!busy && <ArrowRight size={11} weight="bold" />}
                </button>
              </div>
            </div>
          )}

          <div className="text-alloy text-[0.65rem] font-mono pt-1 border-t border-cyan/10">
            Or link a local Ollama / llama.cpp in Settings for zero-cloud mode.
          </div>
        </>
      )}
    </div>
  );
}
