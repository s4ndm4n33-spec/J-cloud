import { useEffect, useState } from "react";
import { X, Key, Trash, CheckCircle, CircleNotch, Stack, Plug, Cpu } from "@phosphor-icons/react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL + "/api";
const PROVIDER_META = {
  openai:    { label: "OpenAI",        note: "Powers GPT-5.2 refinement",          url: "https://platform.openai.com/api-keys" },
  anthropic: { label: "Anthropic",     note: "Powers Claude Sonnet 4.5 governance", url: "https://console.anthropic.com/settings/keys" },
  gemini:    { label: "Google Gemini", note: "Powers Gemini chat",                  url: "https://aistudio.google.com/app/apikey" },
  ollama:    { label: "Local server (Ollama / llama.cpp)", note: "Self-hosted, OpenAI-compat. Last in the failover chain — runs only when cloud providers fail.", url: "https://ollama.com" },
};
const TASK_LABEL = { chat: "Chat", refine: "Refine", governance: "Gauntlet" };

export default function SettingsModal({ onClose }) {
  const [providers, setProviders] = useState([]);
  const [universalKey, setUniversalKey] = useState(true);
  const [chains, setChains] = useState({});
  const [presets, setPresets] = useState({});
  const [drafts, setDrafts] = useState({});
  const [ollamaDraft, setOllamaDraft] = useState({ base_url: "", default_model: "" });
  const [ollamaTest, setOllamaTest] = useState(null); // {ok, models[], backend, error}
  const [busy, setBusy] = useState(null);
  const [toast, setToast] = useState(null);

  async function refresh() {
    const [keysResp, chainResp] = await Promise.all([
      axios.get(`${API}/settings/keys`, { withCredentials: true }),
      axios.get(`${API}/ai/chain`, { withCredentials: true }),
    ]);
    setProviders(keysResp.data.providers);
    setUniversalKey(keysResp.data.universal_key_available);
    setPresets(keysResp.data.ollama_presets || {});
    setChains(chainResp.data.chains);
    const ol = keysResp.data.providers.find((p) => p.provider === "ollama");
    if (ol && ol.configured) {
      setOllamaDraft({ base_url: ol.base_url || "", default_model: ol.default_model || "" });
    }
  }
  useEffect(() => { refresh(); }, []);

  function flash(msg) { setToast(msg); setTimeout(() => setToast(null), 2500); }

  async function save(provider) {
    const api_key = (drafts[provider] || "").trim();
    if (!api_key) return;
    setBusy(provider);
    try {
      await axios.put(`${API}/settings/keys`, { provider, api_key }, { withCredentials: true });
      setDrafts((d) => ({ ...d, [provider]: "" }));
      await refresh();
      flash(`${PROVIDER_META[provider].label} key saved`);
    } catch (e) {
      flash(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(null); }
  }

  async function remove(provider) {
    setBusy(provider);
    try {
      await axios.delete(`${API}/settings/keys/${provider}`, { withCredentials: true });
      if (provider === "ollama") {
        setOllamaDraft({ base_url: "", default_model: "" });
        setOllamaTest(null);
      }
      await refresh();
      flash(`${PROVIDER_META[provider].label} removed`);
    } finally { setBusy(null); }
  }

  async function testOllamaEndpoint() {
    const base_url = ollamaDraft.base_url.trim();
    if (!base_url) { flash("Set a URL first"); return; }
    setBusy("ollama-test");
    setOllamaTest(null);
    try {
      const r = await axios.post(`${API}/settings/keys/ollama/test`, { base_url },
                                 { withCredentials: true });
      setOllamaTest(r.data);
      if (r.data.ok && !ollamaDraft.default_model && (r.data.models || []).length) {
        setOllamaDraft((d) => ({ ...d, default_model: r.data.models[0] }));
      }
    } catch (e) {
      setOllamaTest({ ok: false, error: e?.response?.data?.detail || "Request failed" });
    } finally { setBusy(null); }
  }

  async function saveOllama() {
    const { base_url, default_model } = ollamaDraft;
    if (!base_url.trim() || !default_model.trim()) {
      flash("URL and model are both required");
      return;
    }
    setBusy("ollama-save");
    try {
      await axios.put(`${API}/settings/keys`, {
        provider: "ollama", base_url: base_url.trim(), default_model: default_model.trim(),
      }, { withCredentials: true });
      await refresh();
      flash("Local server linked");
    } catch (e) {
      flash(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(null); }
  }

  const ollamaConfigured = providers.find((p) => p.provider === "ollama")?.configured;

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center bg-midnight/80 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-3xl panel tick-corner relative max-h-[90vh] overflow-auto scrollbar-thin"
        data-testid="settings-modal"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-cyan/15 sticky top-0 bg-midnight z-10">
          <div className="flex items-center gap-2">
            <Key size={14} className="text-cyan" weight="fill" />
            <div className="font-display tracking-[0.25em] text-xs text-cyan">PROVIDER KEYS · FAILOVER CHAIN</div>
          </div>
          <button onClick={onClose} className="text-alloy hover:text-orange" data-testid="settings-close">
            <X size={14} weight="bold" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="font-mono text-[0.7rem] text-alloy leading-relaxed">
            Emergent Universal Key runs first. If it fails, your provider keys engage in the order
            below — same provider, then cross-provider, then your local server — until one succeeds.
            Cloud keys are encrypted at rest (Fernet) and never leave your workspace.
          </div>

          <div
            className="flex items-center justify-between px-3 py-2 border border-cyan/15"
            data-testid="universal-status"
          >
            <div className="flex items-center gap-2">
              {universalKey
                ? <CheckCircle size={14} className="text-viridian" weight="fill" />
                : <X size={14} className="text-orange" />}
              <span className="font-mono text-[0.75rem] text-gridwhite">
                Emergent Universal Key: {universalKey ? "available" : "missing"}
              </span>
            </div>
            <span className="font-mono text-[0.65rem] text-cyan">PRIMARY</span>
          </div>

          {providers.filter((p) => p.provider !== "ollama").map((p) => {
            const meta = PROVIDER_META[p.provider];
            return (
              <div key={p.provider} className="border border-cyan/15 p-3" data-testid={`provider-${p.provider}`}>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-display text-[0.8rem] tracking-[0.15em] text-gridwhite">{meta.label}</div>
                    <div className="font-mono text-[0.65rem] text-alloy">// {meta.note}</div>
                  </div>
                  {p.configured ? (
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[0.7rem] text-viridian" data-testid={`provider-${p.provider}-masked`}>
                        {p.masked}
                      </span>
                      <button
                        onClick={() => remove(p.provider)}
                        disabled={busy === p.provider}
                        className="text-alloy hover:text-orange"
                        title="Remove"
                        data-testid={`provider-${p.provider}-remove`}
                      ><Trash size={14} /></button>
                    </div>
                  ) : (
                    <span className="font-mono text-[0.65rem] text-alloy">// not configured</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    placeholder={p.configured ? "replace key…" : "paste API key…"}
                    value={drafts[p.provider] || ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [p.provider]: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === "Enter") save(p.provider); }}
                    className="flex-1 bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs text-gridwhite"
                    data-testid={`provider-${p.provider}-input`}
                  />
                  <button
                    onClick={() => save(p.provider)}
                    disabled={busy === p.provider || !(drafts[p.provider] || "").trim()}
                    className="btn-solid text-[0.7rem]"
                    data-testid={`provider-${p.provider}-save`}
                  >
                    {busy === p.provider ? <CircleNotch size={12} className="animate-spin" /> : null}
                    SAVE
                  </button>
                </div>
                <a
                  href={meta.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-[0.6rem] text-cyan hover:underline mt-1 inline-block"
                >{`> get a key at ${meta.url.replace(/^https?:\/\//, "")}`}</a>
              </div>
            );
          })}

          {/* Ollama / local server */}
          <div className="border border-cyan/15 p-3" data-testid="provider-ollama">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Cpu size={14} className="text-cyan" weight="fill" />
                <div>
                  <div className="font-display text-[0.8rem] tracking-[0.15em] text-gridwhite">
                    {PROVIDER_META.ollama.label}
                  </div>
                  <div className="font-mono text-[0.65rem] text-alloy">// {PROVIDER_META.ollama.note}</div>
                </div>
              </div>
              {ollamaConfigured ? (
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[0.65rem] text-viridian" data-testid="provider-ollama-masked">
                    LINKED
                  </span>
                  <button
                    onClick={() => remove("ollama")}
                    disabled={busy === "ollama"}
                    className="text-alloy hover:text-orange"
                    title="Remove"
                    data-testid="provider-ollama-remove"
                  ><Trash size={14} /></button>
                </div>
              ) : (
                <span className="font-mono text-[0.65rem] text-alloy">// optional</span>
              )}
            </div>

            <div className="flex gap-1 mb-2">
              {Object.entries(presets).map(([name, url]) => (
                <button
                  key={name}
                  onClick={() => setOllamaDraft((d) => ({ ...d, base_url: url }))}
                  className="font-mono text-[0.6rem] px-2 py-1 border border-cyan/20 text-alloy hover:text-cyan hover:border-cyan/50"
                  data-testid={`ollama-preset-${name}`}
                >{name}</button>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2 mb-2">
              <input
                type="text"
                placeholder="base url (http://host:port)"
                value={ollamaDraft.base_url}
                onChange={(e) => setOllamaDraft((d) => ({ ...d, base_url: e.target.value }))}
                className="bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs text-gridwhite"
                data-testid="ollama-url-input"
              />
              <input
                type="text"
                placeholder="default model (e.g. llama3.1)"
                value={ollamaDraft.default_model}
                onChange={(e) => setOllamaDraft((d) => ({ ...d, default_model: e.target.value }))}
                className="bg-steel border border-cyan/20 px-2 py-1.5 font-mono text-xs text-gridwhite"
                data-testid="ollama-model-input"
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={testOllamaEndpoint}
                disabled={busy === "ollama-test" || !ollamaDraft.base_url.trim()}
                className="px-3 py-1.5 border border-cyan/40 text-cyan font-mono text-[0.7rem] hover:bg-cyan/10 inline-flex items-center gap-1.5"
                data-testid="ollama-test"
              >
                {busy === "ollama-test"
                  ? <CircleNotch size={12} className="animate-spin" />
                  : <Plug size={12} />}
                TEST CONNECTION
              </button>
              <button
                onClick={saveOllama}
                disabled={busy === "ollama-save" || !ollamaDraft.base_url.trim() || !ollamaDraft.default_model.trim()}
                className="btn-solid text-[0.7rem]"
                data-testid="ollama-save"
              >
                {busy === "ollama-save" ? <CircleNotch size={12} className="animate-spin" /> : null}
                LINK SERVER
              </button>
            </div>

            {ollamaTest && (
              <div
                className={`mt-2 p-2 font-mono text-[0.7rem] border ${
                  ollamaTest.ok ? "border-viridian/40 text-viridian" : "border-orange/40 text-orange"
                }`}
                data-testid="ollama-test-result"
              >
                {ollamaTest.ok ? (
                  <>
                    CONNECTED · {ollamaTest.backend} ·{" "}
                    {(ollamaTest.models || []).length
                      ? `${ollamaTest.models.length} model(s): ${ollamaTest.models.slice(0, 6).join(", ")}`
                      : "no models published"}
                  </>
                ) : (
                  <>OFFLINE · {ollamaTest.error}</>
                )}
              </div>
            )}

            <div className="mt-2 font-mono text-[0.6rem] text-alloy leading-relaxed">
              {`> tip: run `}
              <span className="text-cyan">{`ollama serve`}</span>
              {` then `}
              <span className="text-cyan">{`ollama pull llama3.1`}</span>
              {`. Endpoint defaults to localhost:11434. Remote? set the host here and ensure the port is reachable from this workspace.`}
            </div>
          </div>

          <div className="border border-cyan/15 p-3" data-testid="chain-resolved">
            <div className="flex items-center gap-2 mb-3">
              <Stack size={14} className="text-cyan" weight="fill" />
              <div className="font-display text-[0.8rem] tracking-[0.15em] text-gridwhite">RESOLVED CHAIN</div>
              <div className="font-mono text-[0.6rem] text-alloy ml-2">// per-task failover order</div>
            </div>
            {Object.entries(chains).map(([task, steps]) => (
              <div key={task} className="mb-3 last:mb-0" data-testid={`chain-${task}`}>
                <div className="font-mono text-[0.7rem] text-cyan mb-1">// {TASK_LABEL[task] || task}</div>
                <div className="space-y-1">
                  {steps.map((s, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 font-mono text-[0.7rem]"
                      style={{ opacity: s.runnable ? 1 : 0.4 }}
                    >
                      <span
                        className="w-2 h-2 inline-block"
                        style={{ background: s.runnable ? "var(--viridian)" : "rgba(125,133,151,0.3)" }}
                      />
                      <span className="text-alloy w-6">#{i + 1}</span>
                      <span className="text-cyan w-20">{s.source}</span>
                      <span className="text-gridwhite w-20">{s.provider}</span>
                      <span className="text-alloy flex-1 truncate">{s.model}</span>
                      <span
                        className="text-[0.6rem]"
                        style={{ color: s.runnable ? "var(--viridian)" : "var(--alloy-gray)" }}
                      >{s.runnable ? "ARMED" : "SKIP"}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {toast && (
          <div className="absolute bottom-3 right-3 panel px-3 py-2 font-mono text-[0.7rem] text-cyan" data-testid="settings-toast">
            {toast}
          </div>
        )}
      </div>
    </div>
  );
}
