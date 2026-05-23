import { useEffect, useState } from "react";
import { X, Key, Trash, CheckCircle, CircleNotch } from "@phosphor-icons/react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL + "/api";
const PROVIDER_META = {
  openai:    { label: "OpenAI",    note: "Powers GPT-5.2 refinement",            url: "https://platform.openai.com/api-keys" },
  anthropic: { label: "Anthropic", note: "Powers Claude Sonnet 4.5 governance",  url: "https://console.anthropic.com/settings/keys" },
  gemini:    { label: "Google Gemini", note: "Powers Gemini chat",               url: "https://aistudio.google.com/app/apikey" },
};

export default function SettingsModal({ onClose }) {
  const [providers, setProviders] = useState([]);
  const [universalKey, setUniversalKey] = useState(true);
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState(null);
  const [toast, setToast] = useState(null);

  async function refresh() {
    const r = await axios.get(`${API}/settings/keys`, { withCredentials: true });
    setProviders(r.data.providers);
    setUniversalKey(r.data.universal_key_available);
  }
  useEffect(() => { refresh(); }, []);

  function flash(msg) {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }

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
      await refresh();
      flash(`${PROVIDER_META[provider].label} key removed`);
    } finally { setBusy(null); }
  }

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center bg-midnight/80 backdrop-blur-sm" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl panel tick-corner relative"
        data-testid="settings-modal"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-cyan/15">
          <div className="flex items-center gap-2">
            <Key size={14} className="text-cyan" weight="fill" />
            <div className="font-display tracking-[0.25em] text-xs text-cyan">PROVIDER KEYS</div>
          </div>
          <button onClick={onClose} className="text-alloy hover:text-orange" data-testid="settings-close">
            <X size={14} weight="bold" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="font-mono text-[0.7rem] text-alloy leading-relaxed">
            Bring your own keys. J prefers your keys over the Emergent Universal Key when present.
            Keys are encrypted at rest (Fernet) and never leave your workspace.
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
            <span className="font-mono text-[0.65rem] text-alloy">fallback</span>
          </div>

          {providers.map((p) => {
            const meta = PROVIDER_META[p.provider];
            return (
              <div key={p.provider} className="border border-cyan/15 p-3" data-testid={`provider-${p.provider}`}>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-display text-[0.8rem] tracking-[0.15em] text-gridwhite">
                      {meta.label}
                    </div>
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
                      >
                        <Trash size={14} />
                      </button>
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
                >
                  {`> get a key at ${meta.url.replace(/^https?:\/\//, "")}`}
                </a>
              </div>
            );
          })}
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
