import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { initLocalOperator, loginLocalOperator } from "@/lib/api";

const IN_APP_BROWSER_RE = /(FBAN|FBAV|Instagram|Twitter|Line|MicroMessenger|Snapchat|TikTok|Pinterest|LinkedInApp|Discord|Telegram|WhatsApp|GSA|wv\)|; wv;)/i;
const PORTABLE_PROFILE = process.env.REACT_APP_J_CLOUD_PROFILE === "portable";

function isInAppBrowser() {
  if (typeof navigator === "undefined") return false;
  return IN_APP_BROWSER_RE.test(navigator.userAgent || "");
}

export default function SignIn() {
  const { user, loading, setUser } = useAuth();
  const navigate = useNavigate();
  const [inApp, setInApp] = useState(false);
  const [email, setEmail] = useState("operator@local.shard");
  const [name, setName] = useState("Local Operator");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setInApp(isInAppBrowser());
  }, []);

  useEffect(() => {
    if (!loading && user) navigate("/ide", { replace: true });
  }, [user, loading, navigate]);

  function handleGoogle() {
    const redirectUrl = window.location.origin + "/ide";
    window.location.href =
      "https://auth.emergentagent.com/?redirect=" + encodeURIComponent(redirectUrl);
  }

  async function handleLocalSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = { email, name, password };
      const result = mode === "init"
        ? await initLocalOperator(payload)
        : await loginLocalOperator({ email, password });
      setUser(result.user);
      navigate("/ide", { replace: true });
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (mode === "login" && e?.response?.status === 401) {
        setError("Local operator not initialized or credentials were rejected. Use first boot setup if this is a new shard.");
      } else if (typeof detail === "string") {
        setError(detail);
      } else {
        setError("Local authentication failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen w-full flex flex-col bg-midnight text-gridwhite relative overflow-hidden">
      <div className="absolute inset-3 sm:inset-6 border border-cyan/15 pointer-events-none">
        <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-cyan"></div>
        <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-cyan"></div>
        <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-cyan"></div>
        <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-cyan"></div>
      </div>

      <div className="flex items-center justify-between px-5 sm:px-10 py-5 sm:py-6 relative z-10">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 border border-cyan/60 bg-cyan/10 flex items-center justify-center font-display text-cyan" data-testid="brand-logo">J</div>
          <div className="leading-tight">
            <div className="font-display text-[0.65rem] sm:text-[0.7rem] tracking-[0.3em] sm:tracking-[0.35em] text-cyan">SOVEREIGN SHARDS</div>
            <div className="font-mono text-[0.6rem] sm:text-[0.65rem] text-alloy">// GAUNTLET DEVSPACE</div>
          </div>
        </div>
        <div className="hidden sm:block font-mono text-[0.65rem] text-alloy tracking-widest">
          NODE LOCAL · ONLINE
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center px-4 sm:px-6">
        <div className="w-full max-w-xl relative tick-corner panel p-6 sm:p-10">
          <div className="font-mono text-[0.6rem] sm:text-[0.65rem] tracking-[0.25em] text-cyan mb-2">
            // IF IT CAN'T PROVE INTEGRITY, IT HALTS.
          </div>
          <h1 className="font-display text-3xl sm:text-5xl font-extrabold tracking-tight text-gridwhite leading-tight">
            DEPLOY <span className="text-cyan">THE</span> SHARD
          </h1>
          <p className="mt-3 text-alloy text-sm max-w-md">
            J is awake. Five Masters loaded. Sign in to enter your sovereign development environment.
          </p>

          {PORTABLE_PROFILE ? (
            <form className="mt-8 space-y-3" onSubmit={handleLocalSubmit} data-testid="local-auth-form">
              <div className="grid grid-cols-2 gap-2 font-mono text-[0.65rem]">
                <button
                  type="button"
                  data-testid="local-auth-login-mode-btn"
                  onClick={() => setMode("login")}
                  className={mode === "login" ? "btn-solid justify-center py-2" : "btn-ghost justify-center py-2"}
                >
                  LOGIN
                </button>
                <button
                  type="button"
                  data-testid="local-auth-init-mode-btn"
                  onClick={() => setMode("init")}
                  className={mode === "init" ? "btn-solid justify-center py-2" : "btn-ghost justify-center py-2"}
                >
                  FIRST BOOT
                </button>
              </div>
              {mode === "init" && (
                <input
                  data-testid="local-auth-name-input"
                  className="w-full bg-void border border-cyan/25 px-3 py-2 font-mono text-sm text-gridwhite"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="operator name"
                />
              )}
              <input
                data-testid="local-auth-email-input"
                className="w-full bg-void border border-cyan/25 px-3 py-2 font-mono text-sm text-gridwhite"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="operator email"
              />
              <input
                data-testid="local-auth-password-input"
                className="w-full bg-void border border-cyan/25 px-3 py-2 font-mono text-sm text-gridwhite"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="local password"
                type="password"
              />
              {error && (
                <div className="p-3 border border-orange/50 bg-orange/5 font-mono text-[0.7rem] text-orange" data-testid="local-auth-error">
                  {error}
                </div>
              )}
              <button
                data-testid="local-auth-submit-btn"
                type="submit"
                disabled={busy}
                className="w-full btn-solid justify-center py-3 text-[0.7rem] sm:text-[0.8rem] tracking-[0.15em] disabled:opacity-60"
              >
                {busy ? "AUTHENTICATING" : "ENTER LOCAL SHARD"}
              </button>
            </form>
          ) : (
            <button
              data-testid="google-signin-button"
              onClick={handleGoogle}
              className="mt-8 w-full btn-solid justify-center py-3 text-[0.7rem] sm:text-[0.8rem] tracking-[0.15em]"
            >
              INITIALIZE AUTONOMOUS DEVELOPMENT SUBSTRATE
            </button>
          )}

          {inApp && !PORTABLE_PROFILE && (
            <div
              className="mt-4 p-3 border border-orange/50 bg-orange/5 font-mono text-[0.7rem] text-orange leading-relaxed"
              data-testid="inapp-warning"
            >
              <div className="font-display tracking-[0.2em] text-[0.65rem] mb-1">// IN-APP BROWSER DETECTED</div>
              Google blocks sign-in from in-app browsers. Open this page in a system browser before authenticating.
              <div className="mt-2 break-all text-alloy text-[0.65rem]">
                {typeof window !== "undefined" ? window.location.origin : ""}
              </div>
            </div>
          )}

          <div className="mt-6 font-mono text-[0.65rem] text-alloy tracking-widest">
            <span className="text-cyan">/&gt;</span> {PORTABLE_PROFILE ? "LOCAL AUTH · LOCAL STATE · LOCAL INFERENCE" : "ENCRYPTED · ZERO-TELEMETRY · OAUTH 2.0"}
          </div>
        </div>
      </div>

      <div className="px-5 sm:px-10 py-4 sm:py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 font-mono text-[0.55rem] sm:text-[0.65rem] tracking-[0.2em] sm:tracking-[0.3em] text-alloy">
        <div>SOVEREIGN INFRASTRUCTURE <span className="text-cyan">·</span> LOCAL AUTONOMY <span className="text-cyan">·</span> VERIFIABLE EXECUTION</div>
        <div>DETERMINISTIC. AUTONOMOUS. SUBSTRATE.</div>
      </div>
    </div>
  );
}
