import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Plug, PowerOff, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function AliceBlueCard({ status, reload }) {
  const [setupOpen, setSetupOpen] = useState(false);
  const [form, setForm] = useState({ user_id: "", api_key: "" });
  const [busy, setBusy] = useState(false);

  const hasCreds = status?.has_credentials;
  const isAuth = status?.is_authenticated;

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/alice/credentials", form);
      toast.success("Alice Blue credentials saved");
      setSetupOpen(false);
      setForm({ user_id: "", api_key: "" });
      reload?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  const connect = async () => {
    setBusy(true);
    try {
      await api.post("/alice/connect");
      toast.success("Alice Blue session created");
      reload?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Alice Blue connect failed");
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.post("/alice/disconnect");
      toast.success("Alice Blue disconnected");
      reload?.();
    } catch (err) {
      toast.error("Disconnect failed");
    } finally {
      setBusy(false);
    }
  };

  const wipe = async () => {
    if (!window.confirm("Delete saved Alice Blue credentials?")) return;
    try {
      await api.delete("/alice/credentials");
      toast.success("Alice Blue credentials wiped");
      reload?.();
    } catch (err) {
      toast.error("Wipe failed");
    }
  };

  return (
    <Card className="bg-surface-2 border-border rounded-sm" data-testid="alice-card">
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / broker
          </div>
          <CardTitle className="text-lg font-medium">Alice Blue</CardTitle>
        </div>
        <StatusPill isAuth={isAuth} hasCreds={hasCreds} />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 pt-1">
          <Stat label="Credentials" value={hasCreds ? "saved" : "missing"} tone={hasCreds ? "ok" : "warn"} />
          <Stat label="Session" value={isAuth ? "active" : "inactive"} tone={isAuth ? "ok" : "warn"} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSetupOpen(true)}
            data-testid="alice-edit-creds"
            className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
          >
            <Settings2 className="w-3.5 h-3.5 mr-1.5" />
            {hasCreds ? "Edit" : "Add credentials"}
          </Button>
          {hasCreds && !isAuth && (
            <Button
              size="sm"
              onClick={connect}
              disabled={busy}
              data-testid="alice-connect-btn"
              className="rounded-sm h-8 text-xs bg-brand hover:bg-brand/90 text-white"
            >
              <Plug className="w-3.5 h-3.5 mr-1.5" />
              Connect
            </Button>
          )}
          {isAuth && (
            <Button
              size="sm"
              variant="ghost"
              onClick={disconnect}
              disabled={busy}
              data-testid="alice-disconnect-btn"
              className="rounded-sm h-8 text-xs text-muted-foreground hover:text-loss"
            >
              <PowerOff className="w-3.5 h-3.5 mr-1.5" />
              Disconnect
            </Button>
          )}
          {hasCreds && (
            <Button
              size="sm"
              variant="ghost"
              onClick={wipe}
              disabled={busy}
              data-testid="alice-wipe-btn"
              className="rounded-sm h-8 text-xs text-muted-foreground hover:text-loss ml-auto"
            >
              Wipe
            </Button>
          )}
        </div>
      </CardContent>

      <Dialog open={setupOpen} onOpenChange={setSetupOpen}>
        <DialogContent className="bg-surface-2 border-border rounded-sm sm:max-w-lg" data-testid="alice-setup-dialog">
          <DialogHeader>
            <DialogTitle className="font-medium tracking-tight">Alice Blue ANT API</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Create an app at <span className="text-white">ant.aliceblueonline.com → Apps</span> to get your API key.
              Your Alice Blue user id is your login id (e.g. AB1234).
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-3 pt-2">
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                User ID <span className="text-loss">*</span>
              </Label>
              <Input
                required
                value={form.user_id}
                onChange={(e) => setForm((s) => ({ ...s, user_id: e.target.value }))}
                data-testid="alice-user-id-input"
                placeholder="e.g. AB1234"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                API Key <span className="text-loss">*</span>
              </Label>
              <Input
                required
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((s) => ({ ...s, api_key: e.target.value }))}
                data-testid="alice-api-key-input"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
              />
            </div>
            <DialogFooter className="pt-3">
              <Button type="button" variant="ghost" onClick={() => setSetupOpen(false)} className="rounded-sm h-9 text-xs">
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={busy}
                data-testid="alice-save-btn"
                className="rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white"
              >
                {busy ? "Saving..." : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function StatusPill({ isAuth, hasCreds }) {
  let color = "#737373", text = "not configured";
  if (hasCreds && isAuth) { color = "#00C805"; text = "connected"; }
  else if (hasCreds) { color = "#FF9F0A"; text = "needs connect"; }
  return (
    <div className="flex items-center gap-2 border border-border px-2.5 h-7 rounded-sm bg-surface-1 font-mono text-[10px] uppercase tracking-wider">
      <span className="w-1.5 h-1.5 rounded-full pulse-dot" style={{ backgroundColor: color }} />
      <span style={{ color }}>{text}</span>
    </div>
  );
}

function Stat({ label, value, tone = "default" }) {
  const color = tone === "ok" ? "text-profit" : tone === "warn" ? "text-warn" : "text-white";
  return (
    <div className="border border-border p-3 bg-surface-1 rounded-sm">
      <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-sm ${color}`}>{value}</div>
    </div>
  );
}
