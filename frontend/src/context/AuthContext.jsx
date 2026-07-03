import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { me as apiMe, logout as apiLogout } from "@/lib/api";

const AuthContext = createContext({ user: null, loading: true, refresh: () => {}, signOut: () => {} });

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const u = await apiMe();
      setUser(u);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // CRITICAL: If returning from OAuth callback, skip /me — AuthCallback handles it
    const hash = window.location.hash || "";
    const search = window.location.search || "";
    if (hash.includes("session_id=") || search.includes("session_id=")) {
      setLoading(false);
      return;
    }
    refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try { await apiLogout(); } catch {/* noop */}
    setUser(null);
    window.location.href = "/login";
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, signOut, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
