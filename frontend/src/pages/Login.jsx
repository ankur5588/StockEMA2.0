import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Loader2,
  Lock,
  Mail,
  Shield,
  User,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, setSessionToken } from "@/lib/api";

function formatApiError(detail, fallback = "Something went wrong. Please try again.") {
  if (detail == null) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (
      detail
        .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
        .filter(Boolean)
        .join(" ") || fallback
    );
  }
  if (typeof detail === "object" && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const authError = location.state?.authError;
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (window.location.hash?.includes("session_id=")) {
      setChecking(false);
      return;
    }
    (async () => {
      try {
        await api.get("/auth/me");
        navigate("/dashboard", { replace: true });
      } catch (e) {
        setChecking(false);
      }
    })();
  }, [navigate]);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-1 text-muted-foreground text-sm">
        Checking session...
      </div>
    );
  }

  return (
    <div
      className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-surface-1"
      data-testid="login-page"
    >
      {/* Left: visual */}
      <div className="relative hidden lg:block overflow-hidden border-r border-border">
        <img
          src="https://images.unsplash.com/photo-1760978632114-0939f0d60045?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMjd8MHwxfHNlYXJjaHwyfHxhYnN0cmFjdCUyMGRhcmslMjB0ZWNoJTIwdGV4dHVyZSUyMGJhY2tncm91bmR8ZW58MHx8fHwxNzc3ODEzMjEwfDA&ixlib=rb-4.1.0&q=85"
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-60"
        />
        <div className="absolute inset-0 bg-gradient-to-tr from-surface-1 via-surface-1/40 to-transparent" />
        <div className="relative z-10 h-full flex flex-col justify-between p-10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-sm bg-brand flex items-center justify-center">
              <Activity className="w-4 h-4 text-white" strokeWidth={2.2} />
            </div>
            <span className="font-mono text-sm tracking-[0.18em] uppercase">
              CHARTINK<span className="text-brand">•</span>TRADE
            </span>
          </div>

          <div className="space-y-6 max-w-md">
            <p className="text-[11px] tracking-[0.2em] uppercase text-muted-foreground">
              / algorithmic execution layer
            </p>
            <h1 className="text-4xl sm:text-5xl font-medium leading-[1.05] tracking-tight">
              From Chartink signal
              <br />
              <span className="text-brand">to broker order.</span>
              <br />
              In milliseconds.
            </h1>
            <p className="text-sm text-muted-foreground max-w-sm leading-relaxed">
              Connect Kotak Neo, Dhan, Alice Blue. Route Chartink webhooks.
              Place EMA-based stoploss orders on your open positions —
              automatically, daily.
            </p>
            <div className="grid grid-cols-3 gap-4 pt-4">
              <Feature icon={Zap} label="Webhook" value="live" />
              <Feature icon={Activity} label="EMA10" value="daily" />
              <Feature icon={Shield} label="Session" value="encrypted" />
            </div>
          </div>

          <div className="font-mono text-[10px] text-muted-foreground tracking-wider">
            v1.1 · live-trading · NSE / BSE
          </div>
        </div>
      </div>

      {/* Right: auth */}
      <div className="flex items-center justify-center p-8 relative">
        <div className="w-full max-w-sm space-y-6">
          <div className="lg:hidden flex items-center gap-3 mb-6">
            <div className="w-8 h-8 rounded-sm bg-brand flex items-center justify-center">
              <Activity className="w-4 h-4 text-white" strokeWidth={2.2} />
            </div>
            <span className="font-mono text-sm tracking-[0.18em] uppercase">
              CHARTINK<span className="text-brand">•</span>TRADE
            </span>
          </div>

          <div className="space-y-2">
            <p className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              / sign in
            </p>
            <h2 className="text-3xl font-medium tracking-tight">
              Access your terminal
            </h2>
            <p className="text-sm text-muted-foreground">
              Sign in with email & password, or continue with Google.
            </p>
          </div>

          {authError && (
            <div
              className="border border-loss/40 bg-loss/5 rounded-sm p-3 flex items-start gap-2"
              data-testid="auth-error-banner"
            >
              <AlertTriangle className="w-4 h-4 text-loss mt-0.5 shrink-0" />
              <div className="text-xs text-loss leading-relaxed">
                Sign-in failed:{" "}
                <span className="text-white font-mono">{authError}</span>
              </div>
            </div>
          )}

          <AuthTabs onAuthed={(user) =>
            navigate("/dashboard", { replace: true, state: { user } })
          } />

          <div className="pt-4 border-t border-border space-y-2">
            <p className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              / disclaimer
            </p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Live trading tool. Orders from Chartink webhooks and EMA stoploss
              runs will hit your real broker accounts. Paper-trade first.
            </p>
          </div>
        </div>

        <div className="absolute bottom-6 right-8 font-mono text-[10px] text-muted-foreground tracking-wider">
          secure://chartink-trade
        </div>
      </div>
    </div>
  );
}

function AuthTabs({ onAuthed }) {
  const [tab, setTab] = useState("signin");
  return (
    <Tabs value={tab} onValueChange={setTab} className="w-full">
      <TabsList
        className="grid w-full grid-cols-2 bg-surface-2 rounded-sm h-10"
        data-testid="auth-tabs"
      >
        <TabsTrigger
          value="signin"
          className="rounded-sm data-[state=active]:bg-surface-3"
          data-testid="signin-tab"
        >
          Sign in
        </TabsTrigger>
        <TabsTrigger
          value="signup"
          className="rounded-sm data-[state=active]:bg-surface-3"
          data-testid="signup-tab"
        >
          Sign up
        </TabsTrigger>
      </TabsList>

      <TabsContent value="signin" className="space-y-4 pt-4">
        <SignInForm onAuthed={onAuthed} />
        <DividerWithText text="or" />
        <GoogleButton />
      </TabsContent>

      <TabsContent value="signup" className="space-y-4 pt-4">
        <SignUpForm onAuthed={onAuthed} />
        <DividerWithText text="or" />
        <GoogleButton />
      </TabsContent>
    </Tabs>
  );
}

function DividerWithText({ text }) {
  return (
    <div className="relative flex items-center gap-3">
      <div className="flex-1 border-t border-border" />
      <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        {text}
      </span>
      <div className="flex-1 border-t border-border" />
    </div>
  );
}

function GoogleButton() {
  const handleGoogleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS,
    // THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(
      redirectUrl
    )}`;
  };
  return (
    <Button
      onClick={handleGoogleLogin}
      variant="outline"
      data-testid="google-login-button"
      className="w-full h-10 rounded-sm bg-white text-black hover:bg-white/90 border-transparent font-medium text-sm justify-between px-4"
    >
      <span className="flex items-center gap-3">
        <GoogleIcon />
        Continue with Google
      </span>
      <ArrowUpRight className="w-4 h-4" />
    </Button>
  );
}

function SignInForm({ onAuthed }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { data } = await api.post("/auth/login", {
        email: email.trim(),
        password,
      });
      if (data?.session_token) setSessionToken(data.session_token);
      onAuthed(data?.user);
    } catch (err) {
      setError(
        formatApiError(
          err?.response?.data?.detail,
          err?.message || "Sign-in failed."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="signin-form">
      <div className="space-y-1.5">
        <Label htmlFor="signin-email" className="text-xs uppercase tracking-wider text-muted-foreground">
          Email
        </Label>
        <div className="relative">
          <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signin-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            data-testid="signin-email-input"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="signin-password" className="text-xs uppercase tracking-wider text-muted-foreground">
          Password
        </Label>
        <div className="relative">
          <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signin-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            data-testid="signin-password-input"
          />
        </div>
      </div>

      {error && (
        <div
          className="border border-loss/40 bg-loss/5 rounded-sm p-2 text-xs text-loss leading-relaxed"
          data-testid="signin-error"
        >
          {error}
        </div>
      )}

      <Button
        type="submit"
        disabled={busy}
        size="lg"
        className="w-full h-10 rounded-sm bg-brand text-white hover:bg-brand/90 font-medium text-sm"
        data-testid="signin-submit-button"
      >
        {busy ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Signing in...
          </>
        ) : (
          <>Sign in</>
        )}
      </Button>
    </form>
  );
}

function SignUpForm({ onAuthed }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/auth/register", {
        name: name.trim(),
        email: email.trim(),
        password,
      });
      if (data?.session_token) setSessionToken(data.session_token);
      onAuthed(data?.user);
    } catch (err) {
      setError(
        formatApiError(
          err?.response?.data?.detail,
          err?.message || "Sign-up failed."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="signup-form">
      <div className="space-y-1.5">
        <Label htmlFor="signup-name" className="text-xs uppercase tracking-wider text-muted-foreground">
          Name
        </Label>
        <div className="relative">
          <User className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signup-name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            data-testid="signup-name-input"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="signup-email" className="text-xs uppercase tracking-wider text-muted-foreground">
          Email
        </Label>
        <div className="relative">
          <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signup-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            data-testid="signup-email-input"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="signup-password" className="text-xs uppercase tracking-wider text-muted-foreground">
          Password
        </Label>
        <div className="relative">
          <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            minLength={8}
            data-testid="signup-password-input"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="signup-confirm" className="text-xs uppercase tracking-wider text-muted-foreground">
          Confirm password
        </Label>
        <div className="relative">
          <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="signup-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Repeat password"
            className="pl-9 h-10 rounded-sm bg-surface-2 border-border"
            required
            minLength={8}
            data-testid="signup-confirm-input"
          />
        </div>
      </div>

      {error && (
        <div
          className="border border-loss/40 bg-loss/5 rounded-sm p-2 text-xs text-loss leading-relaxed"
          data-testid="signup-error"
        >
          {error}
        </div>
      )}

      <Button
        type="submit"
        disabled={busy}
        size="lg"
        className="w-full h-10 rounded-sm bg-brand text-white hover:bg-brand/90 font-medium text-sm"
        data-testid="signup-submit-button"
      >
        {busy ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Creating account...
          </>
        ) : (
          <>Create account</>
        )}
      </Button>
    </form>
  );
}

function Feature({ icon: Icon, label, value }) {
  return (
    <div className="border border-border p-3 bg-surface-2/60 backdrop-blur-sm">
      <Icon className="w-4 h-4 text-brand mb-2" />
      <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </div>
      <div className="text-xs font-mono mt-0.5">{value}</div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.83z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.83C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}
