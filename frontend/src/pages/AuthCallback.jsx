import { useEffect, useRef } from "react";
import { exchangeSession } from "@/lib/api";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
function extractSessionId() {
  // Emergent returns the id in the URL fragment, but some mobile browsers
  // (Android Chrome via certain redirect chains) strip the fragment and surface
  // it as a query param instead. Support both.
  const hash = window.location.hash || "";
  const hashMatch = hash.match(/session_id=([^&]+)/);
  if (hashMatch) return decodeURIComponent(hashMatch[1]);
  const params = new URLSearchParams(window.location.search || "");
  const q = params.get("session_id");
  return q ? decodeURIComponent(q) : null;
}

export default function AuthCallback() {
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const sessionId = extractSessionId();
    if (!sessionId) {
      window.location.replace("/login");
      return;
    }

    (async () => {
      try {
        await exchangeSession(sessionId);
        // Hard navigate so AuthProvider re-runs /me with the new cookie/token.
        // Avoids any React state race that bounces mobile users back to /login.
        window.location.replace("/ide");
      } catch (e) {
        console.error("Session exchange failed", e);
        window.location.replace("/login");
      }
    })();
  }, []);

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-midnight">
      <div className="font-display text-cyan tracking-[0.3em] text-sm" data-testid="auth-callback-loading">
        DEPLOYING SHARD…
      </div>
    </div>
  );
}
