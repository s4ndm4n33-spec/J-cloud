import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { exchangeSession } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash || "";
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) {
      navigate("/login", { replace: true });
      return;
    }
    const sessionId = decodeURIComponent(m[1]);

    (async () => {
      try {
        const { user } = await exchangeSession(sessionId);
        setUser(user);
        // strip hash and route
        window.history.replaceState({}, "", "/ide");
        navigate("/ide", { replace: true, state: { user } });
      } catch (e) {
        console.error("Session exchange failed", e);
        navigate("/login", { replace: true });
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-midnight">
      <div className="font-display text-cyan tracking-[0.3em] text-sm" data-testid="auth-callback-loading">
        DEPLOYING SHARD…
      </div>
    </div>
  );
}
