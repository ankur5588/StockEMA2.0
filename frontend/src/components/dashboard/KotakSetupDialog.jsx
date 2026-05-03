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

  const set = (k) => (e) =>
    setForm((s) => ({ ...s, [k]: e.target.value }));

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
