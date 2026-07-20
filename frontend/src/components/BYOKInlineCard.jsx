/* Inline BYOK card rendered inside the chat when the backend returns
   401 needs_keys (or 429 daily_cap_reached / 429 rate_limited).

   Flow:
     1. Pick a provider chip (OpenAI / Anthropic / Gemini / Ollama)
     2. Paste key (cloud) or base_url + model (Ollama)  → VERIFY
     3. On verify OK: reveal model dropdown + optional daily-cap input
     4. CONFIRM & RETRY → save + fire onSaved(retry)

   Tone: J is speaking. Sardonic, kind, direct. No dead-ends. */
import { useState } from "react";
import axios from "axios";
import { Key, ArrowRight, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import {
  saveProviderKey, validateProviderKey, API, getStoredToken,
} from "../lib/api";

const CLOUD_PROVIDERS = [
  {
    id: "openai",
    label: "OpenAI",
    tag: "GPT-5.2 · gpt-5.4-mini",
    url: "https://platform.openai.com/api-keys",
    hint: "starts with sk-",
    defaultModel: "gpt-5.2",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    tag: "Claude Sonnet 4.5 · Haiku",
    url: "https://console.anthropic.com/settings/keys",
    hint: "starts with sk-ant-",
    defaultModel: "claude-sonnet-4-5-20250929",
  },
  {
    id: "gemini",
    label: "Gemini",
    tag: "Gemini 3 Flash · 3.1 Pro",
    url: "https://aistudio.google.com/apikey",
    hint: "starts with AIza",
    defaultModel: "gemini-3-flash-preview",
  },
];

const OLLAMA = {
  id: "ollama",
  label: "Ollama",
  tag: "Local · zero cloud cost",
  hint: "http://localhost:11434",
};

export function BYOKInlineCard({ code, onSaved }) {
  const [picked, setPicked] = useState(null); // provider id
  const [apiKey, setApiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [ollamaModel, setOllamaModel] = useState("llama3.1");
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("VERIFYING…");
  const [err, setErr] = useState("");
  const [verified, setVerified] = useState(null); // { models[], message }
  const [chosenModel, setChosenModel] = useState("");
  const [saved, setSaved] = useState(null); // { provider, masked, preferred_model }

  const isTavily = code === "needs_tavily_key";
  const isRateLimited = code === "rate_limited";

  const cloud = CLOUD_PROVIDERS.find((p) => p.id === picked);

  async function handleVerify() {
    if (picked === "ollama") {
      // Test Ollama endpoint via the existing settings/keys/ollama/test route.
      if (!ollamaUrl.trim() || !ollamaModel.trim()) {
        setErr("Both base URL and model are required.");
        return;
      }
      setBusy(true); setErr(""); setBusyLabel("TESTING…");
      try {
        const token = getStoredToken();
        const r = await axios.post(
          `${API}/settings/keys/ollama/test`,
          { base_url: ollamaUrl.trim() },
          {
            withCredentials: true,
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          },
        );
        if (!r.data?.ok) {
          setErr(r.data?.error || "Local server unreachable.");
          setBusy(false); return;
        }
        setVerified({ models: r.data.models || [], message: `Ollama live · ${r.data.backend}` });
        setChosenModel(ollamaModel.trim());
      } catch (e) {
        setErr(e?.response?.data?.detail || e?.message || "Network error reaching Ollama.");
      } finally { setBusy(false); }
      return;
    }
    // Cloud provider flow.
    if (!apiKey.trim()) return;
    setBusy(true); setErr(""); setBusyLabel("VERIFYING…");
    try {
      const v = await validateProviderKey(picked, apiKey.trim());
      if (!v?.ok) {
        setErr(v?.message || "Key rejected by provider. Check for whitespace or a revoked key.");
        setBusy(false); return;
      }
      setVerified({ models: v.models || [], message: v.message || "" });
      // Sensible default: our TASK_CHAINS default for this provider, else
      // the first model in the returned list.
      const def = cloud.defaultModel;
      const chosen = (v.models || []).includes(def) ? def : (v.models?.[0] || def);
      setChosenModel(chosen);
    } catch (e) {
      setErr(
        e?.response?.data?.detail
          || e?.message
          || "Could not reach the provider to verify. Try again.",
      );
    } finally { setBusy(false); }
  }

  async function handleConfirm() {
    if (!picked || !verified) return;
    setBusy(true); setErr(""); setBusyLabel("SAVING…");
    try {
      let payload;
      if (picked === "ollama") {
        const token = getStoredToken();
        const r = await axios.put(
          `${API}/settings/keys`,
          {
            provider: "ollama",
            base_url: ollamaUrl.trim(),
            default_model: chosenModel || ollamaModel.trim(),
          },
          {
            withCredentials: true,
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          },
        );
        payload = { ...r.data, preferred_model: chosenModel || ollamaModel };
      } else {
        payload = await saveProviderKey(picked, apiKey.trim());
        // If the user picked a non-default model, PUT once more with the
        // preferred_model attached (chain default is already correct otherwise).
        if (chosenModel && chosenModel !== cloud.defaultModel) {
          const token = getStoredToken();
          await axios.put(
            `${API}/settings/keys`,
            {
              provider: picked,
              api_key: apiKey.trim(),
              preferred_model: chosenModel,
            },
            {
              withCredentials: true,
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            },
          );
          payload = { ...payload, preferred_model: chosenModel };
        }
      }
      setSaved(payload);
      setTimeout(() => onSaved?.(payload), 700);
    } catch (e) {
      setErr(
        e?.response?.data?.detail
          || e?.message
          || "Save failed — try again.",
      );
    } finally { setBusy(false); }
  }

  // ---- Rendered states ----------------------------------------------------

  if (saved) {
    const step = saved.preferred_model
      ? `${saved.provider} · ${saved.preferred_model}`
      : saved.provider;
    return (
      <div
        className="border border-viridian/40 bg-viridian/5 panel p-3 text-sm space-y-1"
        data-testid="byok-inline-saved"
      >
        <div className="flex items-center gap-2 font-mono text-[0.65rem] tracking-widest text-viridian">
          <CheckCircle size={14} weight="fill" />
          <span>
            {saved.provider.toUpperCase()} SAVED
            {saved.masked ? ` · ${saved.masked}` : ""}
          </span>
        </div>
        <div className="text-alloy text-[0.75rem]">
          J will now use <span className="text-cyan">{step}</span>. Retrying…
        </div>
      </div>
    );
  }

  // Rate limited — friendly card, no key input needed.
  if (isRateLimited) {
    return (
      <div
        className="border border-orange/40 bg-orange/5 panel p-3 text-sm space-y-1"
        data-testid="byok-rate-card"
      >
        <div className="flex items-center gap-2 font-mono text-[0.65rem] tracking-widest text-orange">
          <WarningCircle size={14} weight="fill" />
          <span>SLOW DOWN</span>
        </div>
        <div className="text-gridwhite text-[0.8rem]">
          You&apos;re asking me faster than the rate limiter allows. Give it a beat, then try again.
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
              a provider, verify, save. Encrypted at rest, revocable anytime.
              You pick which of your models I use.
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
            {[...CLOUD_PROVIDERS, OLLAMA].map((p) => {
              const active = picked === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setPicked(p.id);
                    setErr("");
                    setVerified(null);
                    setChosenModel("");
                  }}
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

          {picked && !verified && picked !== "ollama" && (
            <div className="space-y-2 pt-1" data-testid="byok-input-row">
              <div className="flex items-center justify-between">
                <div className="font-mono text-[0.65rem] text-alloy">{cloud.tag}</div>
                <a
                  href={cloud.url}
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
                  if (e.key === "Enter" && !busy && apiKey.trim()) handleVerify();
                }}
                placeholder={cloud.hint}
                className="w-full bg-steel border border-cyan/30 focus:border-cyan px-2 py-1.5 font-mono text-[0.75rem] text-gridwhite outline-none"
                data-testid="byok-key-input"
              />
              <VerifyRow busy={busy} busyLabel={busyLabel} err={err}
                onClick={handleVerify} disabled={!apiKey.trim() || busy}
                label="VERIFY" testid="byok-verify-btn" />
            </div>
          )}

          {picked === "ollama" && !verified && (
            <div className="space-y-2 pt-1" data-testid="byok-ollama-row">
              <div className="font-mono text-[0.65rem] text-alloy">{OLLAMA.tag}</div>
              <input
                type="text"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
                placeholder="http://localhost:11434"
                className="w-full bg-steel border border-cyan/30 focus:border-cyan px-2 py-1.5 font-mono text-[0.7rem] text-gridwhite outline-none"
                data-testid="byok-ollama-url"
              />
              <input
                type="text"
                value={ollamaModel}
                onChange={(e) => setOllamaModel(e.target.value)}
                placeholder="model (e.g. llama3.1)"
                className="w-full bg-steel border border-cyan/30 focus:border-cyan px-2 py-1.5 font-mono text-[0.7rem] text-gridwhite outline-none"
                data-testid="byok-ollama-model"
              />
              <VerifyRow busy={busy} busyLabel={busyLabel} err={err}
                onClick={handleVerify}
                disabled={!ollamaUrl.trim() || !ollamaModel.trim() || busy}
                label="TEST CONNECTION" testid="byok-verify-btn" />
            </div>
          )}

          {verified && (
            <div className="space-y-2 pt-1 border-t border-cyan/10 pt-2"
                 data-testid="byok-verified-row">
              <div className="flex items-center gap-1.5 font-mono text-[0.65rem] text-viridian">
                <CheckCircle size={11} weight="fill" />
                <span>{verified.message}</span>
              </div>

              {verified.models.length > 0 && (
                <div className="space-y-1">
                  <label className="block font-mono text-[0.6rem] tracking-widest text-alloy">
                    MODEL J WILL USE
                  </label>
                  <select
                    value={chosenModel}
                    onChange={(e) => setChosenModel(e.target.value)}
                    className="w-full bg-steel border border-cyan/30 focus:border-cyan px-2 py-1.5 font-mono text-[0.7rem] text-gridwhite outline-none"
                    data-testid="byok-model-picker"
                  >
                    {verified.models.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
              {picked !== "ollama"
                && cloud && !verified.models.includes(cloud.defaultModel) && (
                    <option value={cloud.defaultModel}>
                      {cloud.defaultModel} (chain default)
                    </option>
              )}
                  </select>
                </div>
              )}

              <VerifyRow busy={busy} busyLabel={busyLabel} err={err}
                onClick={handleConfirm} disabled={busy}
                label="CONFIRM & RETRY" testid="byok-save-btn" />
            </div>
          )}

          {!picked && (
            <div className="text-alloy text-[0.65rem] font-mono pt-1 border-t border-cyan/10">
              Cloud costs money · Ollama is free but needs a local server.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function VerifyRow({ busy, busyLabel, err, onClick, disabled, label, testid }) {
  return (
    <div className="flex items-center justify-between">
      {err ? (
        <div
          className="flex items-center gap-1 text-orange text-[0.7rem] pr-2"
          data-testid="byok-error"
        >
          <WarningCircle size={11} weight="fill" />
          <span>{typeof err === "string" ? err : JSON.stringify(err)}</span>
        </div>
      ) : <span />}
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className="flex items-center gap-1.5 px-3 py-1 font-mono text-[0.7rem] tracking-widest border border-cyan text-cyan hover:bg-cyan hover:text-void disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-cyan transition-colors whitespace-nowrap"
        data-testid={testid}
      >
        {busy ? busyLabel : label}
        {!busy && <ArrowRight size={11} weight="bold" />}
      </button>
    </div>
  );
}
