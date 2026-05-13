import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Check, X, AlertTriangle, FlaskConical } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function KotakSetupDialog({ open, onOpenChange, reload }) {
  const [form, setForm] = useState({
    mobile: "",
    password: "",
    mpin: "",
    consumer_key: "",
    consumer_secret: "",
  });
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [oauthResult, setOauthResult] = useState(null);

  const set = (k) => (e) =>
    setForm((s) => ({ ...s, [k]: e.target.value }));

  const testOauth = async () => {
    if (!form.consumer_key.trim() || !form.consumer_secret.trim()) {
      toast.error("Enter consumer_key and consumer_secret first");
      return;
    }
    setTesting(true);
    setOauthResult(null);
    try {
      const res = await api.post("/kotak/test-oauth", {
        consumer_key: form.consumer_key,
        consumer_secret: form.consumer_secret,
        environment: "prod",
      });
      setOauthResult(res.data);
      if (res.data.ok) {
        toast.success("Kotak accepted your key/secret");
      } else {
        toast.error("Kotak rejected — see details below");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Test failed");
      setOauthResult({ ok: false, message: err?.response?.data?.detail || "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/kotak/credentials", form);
      toast.success("Credentials encrypted and saved to your vault");
      onOpenChange(false);
      reload?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-surface-2 border-border rounded-sm sm:max-w-lg"
        data-testid="kotak-setup-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-medium tracking-tight">
            Kotak Neo Credentials
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Stored encrypted (Fernet) in your vault. Required for OTP-based
            login and order routing.
          </DialogDescription>
        </DialogHeader>
        <div
          className="border border-warn/40 bg-warn/5 rounded-sm p-3 text-[11px] text-muted-foreground space-y-1.5"
          data-testid="kotak-setup-tips"
        >
          <div className="text-[10px] uppercase tracking-[0.15em] text-warn font-semibold">
            Before saving — common gotchas
          </div>
          <ul className="list-disc list-inside space-y-0.5 leading-relaxed">
            <li>Use <span className="text-white">TRADE API</span> keys (not Data API)</li>
            <li>New apps can take up to <span className="text-white">24 hours</span> to activate</li>
            <li>Mobile must include country code (e.g. <span className="font-mono">+91...</span>)</li>
            <li>Paste carefully — trailing spaces break the session init</li>
          </ul>
        </div>
        <form className="space-y-3 pt-2" onSubmit={submit}>
          <Field
            label="Mobile number"
            hint="With country code e.g. +919999999999"
            required
            value={form.mobile}
            onChange={set("mobile")}
            testid="kotak-mobile-input"
            placeholder="+91XXXXXXXXXX"
          />
          <Field
            label="Password"
            required
            type="password"
            value={form.password}
            onChange={set("password")}
            testid="kotak-password-input"
          />
          <Field
            label="MPIN"
            required
            type="password"
            value={form.mpin}
            onChange={set("mpin")}
            testid="kotak-mpin-input"
            placeholder="6-digit MPIN"
          />
          <Field
            label="Consumer Key"
            required
            value={form.consumer_key}
            onChange={set("consumer_key")}
            testid="kotak-ckey-input"
          />
          <Field
            label="Consumer Secret"
            required
            type="password"
            value={form.consumer_secret}
            onChange={set("consumer_secret")}
            testid="kotak-csecret-input"
          />

          <Button
            type="button"
            variant="outline"
            onClick={testOauth}
            disabled={testing || !form.consumer_key.trim() || !form.consumer_secret.trim()}
            data-testid="test-oauth-button"
            className="w-full rounded-sm h-9 text-xs border-border bg-surface-1 hover:bg-surface-3"
          >
            <FlaskConical className="w-3.5 h-3.5 mr-1.5" />
            {testing ? "Calling Kotak OAuth..." : "Test key + secret only (no OTP)"}
          </Button>

          {oauthResult && (
            <div
              className={`border rounded-sm p-3 space-y-1.5 ${
                oauthResult.ok
                  ? "border-profit/40 bg-profit/5"
                  : "border-loss/40 bg-loss/5"
              }`}
              data-testid="oauth-test-result"
            >
              <div className="flex items-center gap-2">
                {oauthResult.ok ? (
                  <Check className="w-3.5 h-3.5 text-profit" />
                ) : (
                  <X className="w-3.5 h-3.5 text-loss" />
                )}
                <span
                  className={`text-[10px] uppercase tracking-[0.15em] font-semibold ${
                    oauthResult.ok ? "text-profit" : "text-loss"
                  }`}
                >
                  {oauthResult.ok ? "credentials valid" : "kotak rejected"}
                </span>
                {oauthResult.http_status > 0 && (
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    HTTP {oauthResult.http_status}
                  </span>
                )}
              </div>
              <div className="font-mono text-[11px] text-muted-foreground break-words">
                {oauthResult.message}
              </div>
              {!oauthResult.ok && (
                <div className="text-[10px] text-muted-foreground pt-1 border-t border-border flex items-start gap-1.5">
                  <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                  <span>
                    Check on Kotak Neo dashboard: (1) app status ACTIVE,
                    (2) keys are the latest pair (regen invalidates old),
                    (3) Trade API not Data API, (4) no trailing spaces.
                  </span>
                </div>
              )}
            </div>
          )}
          <DialogFooter className="pt-3">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              className="rounded-sm h-9 text-xs"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={busy}
              data-testid="save-kotak-creds-button"
              className="rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white"
            >
              {busy ? "Saving..." : "Save to vault"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, hint, required, testid, ...rest }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        {label}
        {required && <span className="text-loss ml-1">*</span>}
      </Label>
      <Input
        {...rest}
        required={required}
        data-testid={testid}
        className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs focus-visible:ring-brand"
      />
      {hint && (
        <div className="text-[10px] text-muted-foreground">{hint}</div>
      )}
    </div>
  );
}
