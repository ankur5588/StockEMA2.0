import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function AlertsConfig() {
  const [alerts, setAlerts] = useState([]);
  const [form, setForm] = useState({
    alert_name: "",
    transaction_type: "B",
    quantity: 1,
    exchange_segment: "nse_cm",
    product: "CNC",
    broker: "kotak_neo",
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/alerts");
      setAlerts(res.data.alerts || []);
    } catch (e) {
      toast.error("Failed to load alerts");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const add = async (e) => {
    e.preventDefault();
    if (!form.alert_name.trim()) {
      toast.error("Enter alert name (must match Chartink alert)");
      return;
    }
    setBusy(true);
    try {
      await api.post("/alerts", {
        ...form,
        quantity: Number(form.quantity) || 1,
      });
      toast.success("Alert config added");
      setForm((s) => ({ ...s, alert_name: "", quantity: 1 }));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to add");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/alerts/${id}`);
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error("Failed to delete");
    }
  };

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm h-full"
      data-testid="alerts-config-card"
    >
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / routing
        </div>
        <CardTitle className="text-lg font-medium">Alert Configs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          onSubmit={add}
          className="grid grid-cols-1 sm:grid-cols-7 gap-2"
          data-testid="add-alert-form"
        >
          <div className="sm:col-span-2 space-y-1.5">
            <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Alert name
            </Label>
            <Input
              value={form.alert_name}
              onChange={(e) =>
                setForm((s) => ({ ...s, alert_name: e.target.value }))
              }
              placeholder="exact chartink alert name"
              data-testid="alert-name-input"
              className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Broker
            </Label>
            <Select
              value={form.broker}
              onValueChange={(v) => setForm((s) => ({ ...s, broker: v }))}
            >
              <SelectTrigger
                data-testid="alert-broker-select"
                className="h-9 rounded-sm bg-surface-1 border-border text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="kotak_neo">Kotak</SelectItem>
                <SelectItem value="dhan">Dhan</SelectItem>
                <SelectItem value="alice_blue">Alice</SelectItem>
                <SelectItem value="indmoney">INDmoney</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Side
            </Label>
            <Select
              value={form.transaction_type}
              onValueChange={(v) =>
                setForm((s) => ({ ...s, transaction_type: v }))
              }
            >
              <SelectTrigger
                data-testid="alert-side-select"
                className="h-9 rounded-sm bg-surface-1 border-border text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="B">BUY</SelectItem>
                <SelectItem value="S">SELL</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Qty
            </Label>
            <Input
              type="number"
              min={1}
              value={form.quantity}
              onChange={(e) =>
                setForm((s) => ({ ...s, quantity: e.target.value }))
              }
              data-testid="alert-qty-input"
              className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Product
            </Label>
            <Select
              value={form.product}
              onValueChange={(v) => setForm((s) => ({ ...s, product: v }))}
            >
              <SelectTrigger
                data-testid="alert-product-select"
                className="h-9 rounded-sm bg-surface-1 border-border text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="CNC">CNC</SelectItem>
                <SelectItem value="MIS">MIS</SelectItem>
                <SelectItem value="NRML">NRML</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end">
            <Button
              type="submit"
              disabled={busy}
              data-testid="add-alert-button"
              className="w-full rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add
            </Button>
          </div>
        </form>

        <div className="border border-border rounded-sm divide-y divide-border">
          {alerts.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">
              No alert configs yet.
            </div>
          ) : (
            alerts.map((a) => (
              <div
                key={a.id}
                className="flex items-center gap-3 px-3 py-2.5 hover:bg-surface-3"
                data-testid="alert-row"
              >
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    a.enabled ? "bg-profit" : "bg-muted-foreground"
                  }`}
                />
                <span className="font-mono text-xs flex-1 truncate">
                  {a.alert_name}
                </span>
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-border bg-surface-1 text-muted-foreground uppercase tracking-wider">
                  {a.broker === "kotak_neo" ? "Kotak" : a.broker === "dhan" ? "Dhan" : a.broker === "alice_blue" ? "Alice" : a.broker === "indmoney" ? "INDmoney" : (a.broker || "—")}
                </span>
                <span
                  className={`font-mono text-[10px] px-2 py-0.5 rounded-sm border ${
                    a.transaction_type === "B"
                      ? "border-profit/30 text-profit bg-profit/10"
                      : "border-loss/30 text-loss bg-loss/10"
                  }`}
                >
                  {a.transaction_type === "B" ? "BUY" : "SELL"}
                </span>
                <span className="font-mono text-xs text-muted-foreground tabular-nums w-10 text-right">
                  ×{a.quantity}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {a.product}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => remove(a.id)}
                  data-testid="delete-alert-button"
                  className="h-7 w-7 p-0 rounded-sm text-muted-foreground hover:text-loss"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
