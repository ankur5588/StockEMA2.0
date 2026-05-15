import React, { useEffect, useState } from "react";
import "@/App.css";
import {
  BrowserRouter,
  Routes,
  Route,
  useLocation,
  useNavigate,
  Navigate,
} from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import { api, setSessionToken, clearSessionToken } from "@/lib/api";

// Module-level promise tracking the in-flight OAuth exchange. Survives
// component remounts (React Strict Mode mounts → unmounts → remounts effects).
// Without this, the second remount sees no hash (already stripped) and bounces
// the user back to /login before the first POST resolves.
let _inflightAuth = null;

function AuthCallback() {
  const navigate = useNavigate();
  useEffect(() => {
    const hash = window.location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);

    // Helper: route based on whether we already have a valid token
    const routeWithoutHash = () => {
      const hasToken = !!localStorage.getItem("chartink_session_token");
      navigate(hasToken ? "/dashboard" : "/login", { replace: true });
    };

    if (!match) {
      // No session_id in hash. If a prior mount kicked off the POST, await it.
      if (_inflightAuth) {
        _inflightAuth
          .then((data) => {
            navigate("/dashboard", { replace: true, state: { user: data.user } });
          })
          .catch(() => routeWithoutHash());
      } else {
        routeWithoutHash();
      }
      return;
    }

    const sessionId = decodeURIComponent(match[1]);

    // Start the exchange exactly once per session_id, even across remounts
    if (!_inflightAuth) {
      _inflightAuth = api
        .post("/auth/session", { session_id: sessionId })
        .then((res) => {
          if (res.data?.session_token) {
            setSessionToken(res.data.session_token);
          }
          return res.data;
        });
    }

    _inflightAuth
      .then((data) => {
        window.history.replaceState(null, "", "/dashboard");
        navigate("/dashboard", { replace: true, state: { user: data.user } });
      })
      .catch((e) => {
        clearSessionToken();
        _inflightAuth = null;
        // Surface the most useful failure reason we can:
        // - axios network error: e.message (e.g., "Network Error", "timeout of...")
        // - HTTP error: e.response.status + e.response.data.detail
        let reason = "Login failed";
        if (e?.response) {
          reason = `${e.response.status} ${
            e.response.data?.detail || e.response.statusText || "error"
          }`;
        } else if (e?.message) {
          reason = e.message;
        }
        // eslint-disable-next-line no-console
        console.error("[auth] /auth/session failed:", e, "reason:", reason);
        navigate("/login", {
          replace: true,
          state: { authError: reason },
        });
      });
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-1 text-muted-foreground text-sm">
      Signing you in...
    </div>
  );
}

function ProtectedRoute({ children }) {
  const location = useLocation();
  const passedUser = location.state?.user;
  const [auth, setAuth] = useState(passedUser ? true : null);
  const [user, setUser] = useState(passedUser || null);

  useEffect(() => {
    if (passedUser) return;
    (async () => {
      try {
        const res = await api.get("/auth/me");
        setUser(res.data);
        setAuth(true);
      } catch (e) {
        setAuth(false);
      }
    })();
  }, [passedUser]);

  if (auth === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-1 text-muted-foreground text-sm">
        Loading...
      </div>
    );
  }
  if (!auth) return <Navigate to="/login" replace />;
  return React.cloneElement(children, { user });
}

function AppRouter() {
  const location = useLocation();
  // Synchronously intercept OAuth redirect callback (session_id in hash)
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRouter />
      <Toaster theme="dark" richColors closeButton position="top-right" />
    </BrowserRouter>
  );
}
