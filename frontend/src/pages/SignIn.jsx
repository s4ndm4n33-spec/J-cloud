import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

const LOGO_URL =
  "https://static.prod-images.emergentagent.com/jobs/9f05830c-98fc-45b2-9802-59ed95a81ea4/images/19195be13f453611a4e6f74609c0e5103632c06cef4ee0bd02591a172f1b10c1.png";

export default function SignIn() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user) navigate("/ide", { replace: true });
  }, [user, loading, navigate]);

  function handleGoogle() {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/ide";
    window.location.href =
      "https://auth.emergentagent.com/?redirect=" + encodeURIComponent(redirectUrl);
  }

  return (
    <div className="min-h-screen w-full flex flex-col bg-midnight text-gridwhite relative overflow-hidden">
      {/* HUD frame */}
      <div className="absolute inset-3 sm:inset-6 border border-cyan/15 pointer-events-none">
        <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-cyan"></div>
        <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-cyan"></div>
        <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-cyan"></div>
        <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-cyan"></div>
      </div>

      {/* Top brand bar */}
      <div className="flex items-center justify-between px-5 sm:px-10 py-5 sm:py-6 relative z-10">
        <div className="flex items-center gap-3">
          <img src={LOGO_URL} alt="Sovereign Shards" className="h-9 w-9" data-testid="brand-logo" />
          <div className="leading-tight">
            <div className="font-display text-[0.65rem] sm:text-[0.7rem] tracking-[0.3em] sm:tracking-[0.35em] text-cyan">SOVEREIGN SHARDS</div>
            <div className="font-mono text-[0.6rem] sm:text-[0.65rem] text-alloy">// GAUNTLET DEVSPACE</div>
          </div>
        </div>
        <div className="hidden sm:block font-mono text-[0.65rem] text-alloy tracking-widest">
          NODE {Math.random().toString(36).slice(2, 8).toUpperCase()} · ONLINE
        </div>
      </div>

      {/* Centered login card */}
      <div className="flex-1 flex items-center justify-center px-4 sm:px-6">
        <div className="w-full max-w-xl relative tick-corner panel p-6 sm:p-10">
          <div className="font-mono text-[0.6rem] sm:text-[0.65rem] tracking-[0.25em] text-cyan mb-2">
            // IF IT CAN'T PROVE INTEGRITY, IT HALTS.
          </div>
          <h1 className="font-display text-3xl sm:text-5xl font-extrabold tracking-tight text-gridwhite leading-tight">
            DEPLOY <span className="text-cyan">THE</span> SHARD
          </h1>
          <p className="mt-3 text-alloy text-sm max-w-md">
            J is awake. Five Masters loaded. Sardonic wit module engaged. Sign in to enter your
            sovereign cloud development environment.
          </p>

          <button
            data-testid="google-signin-button"
            onClick={handleGoogle}
            className="mt-8 w-full btn-solid justify-center py-3 text-[0.85rem]"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" className="-ml-1">
              <path fill="#0B0F14" d="M17.64 9.205c0-.638-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.614z"/>
              <path fill="#0B0F14" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z"/>
              <path fill="#0B0F14" d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>
              <path fill="#0B0F14" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
            </svg>
            CONTINUE WITH GOOGLE
          </button>

          <div className="mt-6 font-mono text-[0.65rem] text-alloy tracking-widest">
            <span className="text-cyan">/&gt;</span> ENCRYPTED · ZERO-TELEMETRY · OAUTH 2.0
          </div>
        </div>
      </div>

      {/* Brand pillars footer */}
      <div className="px-5 sm:px-10 py-4 sm:py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 font-mono text-[0.55rem] sm:text-[0.65rem] tracking-[0.2em] sm:tracking-[0.3em] text-alloy">
        <div>SOVEREIGN INFRASTRUCTURE <span className="text-cyan">·</span> LOCAL AUTONOMY <span className="text-cyan">·</span> VERIFIABLE EXECUTION</div>
        <div>DETERMINISTIC. AUTONOMOUS. SUBSTRATE.</div>
      </div>
    </div>
  );
}
