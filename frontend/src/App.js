import { useEffect } from "react";
import { BrowserRouter, Routes, Route, useLocation, Navigate } from "react-router-dom";
import "@/App.css";
import SignIn from "@/pages/SignIn";
import AuthCallback from "@/pages/AuthCallback";
import IDE from "@/pages/IDE";
import { useAuth, AuthProvider } from "@/context/AuthContext";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-midnight text-cyan font-display tracking-widest text-sm">
        <span data-testid="auth-loading">VERIFYING SHARD…</span>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppRouter() {
  const location = useLocation();
  // Race-free OAuth callback handling — fragment containing session_id wins
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/login" element={<SignIn />} />
      <Route
        path="/ide"
        element={
          <ProtectedRoute>
            <IDE />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/ide" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
