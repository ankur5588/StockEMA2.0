import React, { useEffect, useMemo, useState } from "react";
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
import { Switch } from "@/components/ui/switch";
import { Loader2, Send, Moon, ShieldAlert, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const BROKERS = [
  { value: "kotak_neo", label: "Kotak Neo" },
  { value: "dhan", label: "Dhan" },
  { value: "alice_blue", label: "Alice Blue" },
];

const EXCHANGES = [
  { value: "nse_cm", label: "NSE" },
  { value: "bse_cm", label: "BSE" },
];

const ORDER_TYPES = [
  { value: "MKT", label: "Market" },
  { value: "L", label: "Limit" },
];

const PRODUCTS = [
  { value: "CNC", label: "CNC / Delivery" },
  { value: "MIS", label: "MIS / Intraday" },
  { value: "NRML", label: "NRML / Margin" },
];

const blank = {
  broker: "kotak_neo",
  symbol: "",
  transaction_type: "B",
  quantity: "",
  order_type: "MKT",
  price: "",
  product: "CNC",
  exchange_segment: "nse_cm",
  amo: false,
  auto_ema_sl: true,
};

export default function ManualOrderCard({ brokersStatus, reload }) {
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [emaPreview, setEmaPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const connectedBrokers = useMemo(() => {
    if (!brokersStatus) return [];
    return BROKERS.filter((b) => brokersStatus[b.value]?.is_authenticated);
  }, [brokersStatus]);

  // Default to the first connected broker on mount / when statuses update
  useEffect(() => {
    if (connectedBrokers.length > 0 && !connectedBrokers.find((b) => b.value === form.broker)) {
      setForm((s) => ({ ...s, broker: connectedBrokers[0].value }));
    }
  }, [connectedBrokers, form.broker]);

  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const previewEma = async () => {
    if (!form.symbol.trim()) {
      toast.error("Enter a symbol first");
      return;
    }
    setPreviewing(true);
    setEmaPreview(null);
    try {
      const res = await api.get(
        `/ema-preview/${encodeURIComponent(form.symbol.trim().toUpperCase())}?exchange_segment=${form.exchange_segment}`
      );
      setEmaPreview(res.data);
      if (res.data?.ema10 == null) {
        toast.error("No historical data available for this symbol");
      }
    } catch (e) {
      toast.error("Failed to fetch EMA10");
    } finally {
      setPreviewing(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.symbol.trim()) return toast.error("Symbol is required");
    if (!form.quantity || Number(form.quantity) <= 0)
      return toast.error("Quantity must be > 0");
    if (form.order_type === "L" && (!form.price || Number(form.price) <= 0))
      return toast.error("Price required for Limit orders");

    setBusy(true);
    setLastResult(null);
    try {
      const payload = {
        broker: form.broker,
        symbol: form.symbol.trim().toUpperCase(),
        transaction_type: form.transaction_type,
        quantity: Number(form.quantity),
        order_type: form.order_type,
        price: form.order_type === "L" ? Number(form.price) : 0,
        product: form.product,
        exchange_segment: form.exchange_segment,
        amo: !!form.amo,
        auto_ema_sl: !!form.auto_ema_sl && form.transaction_type === "B",
      };
      const res = await api.post("/orders/manual", payload);
      const data = res.data || {};
      setLastResult(data);
      if (data.status === "success") {
        toast.success(
          `Order placed${
            data.ema_sl?.status === "placed"
              ? ` + EMA SL @ ₹${data.ema_sl.ema10}`
              : data.ema_sl?.status === "skipped"
              ? ` (SL: ${data.ema_sl.message})`
              : ""
          }`
        );
      } else if (data.status === "skipped") {
        toast.error(data.message || "Broker not connected. Connect a broker first.");
      } else {
        toast.error(data.message || "Order was not placed");
      }
      reload?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : detail?.[0]?.msg ||
            err?.response?.statusText ||
            err?.message ||
            "Order failed";
      setLastResult({ status: "error", message: msg, ema_sl: null });
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const sideIsBuy = form.transaction_type === "B";

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm"
      data-testid="manual-order-card"
    >
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / manual order
        </div>
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <Send className="w-4 h-4 text-brand" />
          Place an order
        </CardTitle>
        <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
          Place a market or limit order on any connected broker. Toggle{" "}
          <span className="text-white">After-market</span> to queue it for the
          next session, or <span className="text-white">Auto EMA10 SL</span> to
          automatically attach a stoploss-sell at the EMA10 trigger.
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4" data-testid="manual-order-form">
          {/* Row 1: broker + symbol + side */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
            <SelectField
              label="Broker"
              value={form.broker}
              onChange={(v) => set("broker", v)}
              testid="mo-broker-select"
              options={BROKERS.map((b) => ({
                ...b,
                label: brokersStatus?.[b.value]?.is_authenticated
                  ? b.label
                  : `${b.label} (offline)`,
              }))}
              className="md:col-span-2"
            />
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Symbol
              </Label>
              <Input
                value={form.symbol}
                onChange={(e) => set("symbol", e.target.value)}
                placeholder="RELIANCE-EQ"
                data-testid="mo-symbol-input"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs uppercase"
              />
            </div>
            <SelectField
              label="Side"
              value={form.transaction_type}
              onChange={(v) => set("transaction_type", v)}
              testid="mo-side-select"
              options={[
                { value: "B", label: "BUY" },
                { value: "S", label: "SELL" },
              ]}
            />
            <SelectField
              label="Exchange"
              value={form.exchange_segment}
              onChange={(v) => set("exchange_segment", v)}
              options={EXCHANGES}
              testid="mo-exchange-select"
            />
          </div>

          {/* Row 2: qty + order_type + price + product */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Qty
              </Label>
              <Input
                type="number"
                min="1"
                value={form.quantity}
                onChange={(e) => set("quantity", e.target.value)}
                placeholder="1"
                data-testid="mo-quantity-input"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
              />
            </div>
            <SelectField
              label="Order type"
              value={form.order_type}
              onChange={(v) => set("order_type", v)}
              options={ORDER_TYPES}
              testid="mo-order-type-select"
            />
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Price {form.order_type === "MKT" && <span className="opacity-50">(market)</span>}
              </Label>
              <Input
                type="number"
                step="0.05"
                value={form.price}
                onChange={(e) => set("price", e.target.value)}
                placeholder={form.order_type === "MKT" ? "—" : "0.00"}
                disabled={form.order_type === "MKT"}
                data-testid="mo-price-input"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs disabled:opacity-40"
              />
            </div>
            <SelectField
              label="Product"
              value={form.product}
              onChange={(v) => set("product", v)}
              options={PRODUCTS}
              testid="mo-product-select"
            />
          </div>

          {/* Row 3: toggles */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <ToggleBlock
              icon={Moon}
              title="After-Market Order"
              hint="Queue for the next session. Use outside 9:15–15:30 IST."
              checked={form.amo}
              onCheckedChange={(v) => set("amo", v)}
              testid="mo-amo-switch"
            />
            <ToggleBlock
              icon={ShieldAlert}
              title="Auto EMA10 stoploss"
              hint={
                sideIsBuy
                  ? "After a BUY fill, place a SL-Sell at the daily EMA10."
                  : "Only applies to BUY entries — disabled for SELL."
              }
              checked={form.auto_ema_sl && sideIsBuy}
              onCheckedChange={(v) => set("auto_ema_sl", v)}
              disabled={!sideIsBuy}
              testid="mo-auto-sl-switch"
            />
          </div>

          {/* EMA preview row */}
          {sideIsBuy && form.auto_ema_sl && (
            <div className="border border-dashed border-border rounded-sm p-3 flex flex-col sm:flex-row sm:items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={previewEma}
                disabled={previewing || !form.symbol.trim()}
                data-testid="mo-preview-ema-button"
                className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
              >
                {previewing ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                    Fetching...
                  </>
                ) : (
                  <>
                    <TrendingUp className="w-3.5 h-3.5 mr-1.5" />
                    Preview EMA10
                  </>
                )}
              </Button>
              {emaPreview && (
                <div
                  className="flex-1 grid grid-cols-3 gap-3 text-[11px] font-mono"
                  data-testid="mo-ema-preview"
                >
                  <PreviewCell label="EMA10" value={emaPreview.ema10 ? `₹${emaPreview.ema10}` : "—"} />
                  <PreviewCell label="SL trigger" value={emaPreview.sl_trigger ? `₹${emaPreview.sl_trigger}` : "—"} accent="text-loss" />
                  <PreviewCell label="SL limit" value={emaPreview.sl_limit ? `₹${emaPreview.sl_limit}` : "—"} />
                </div>
              )}
              {!emaPreview && (
                <p className="text-[11px] text-muted-foreground">
                  EMA10 is computed from yfinance daily closes — last 3 months.
                </p>
              )}
            </div>
          )}

          {/* Submit */}
          <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-2 pt-1">
            {lastResult && (
              <div
                className={`text-[11px] font-mono ${
                  lastResult.status === "success"
                    ? "text-profit"
                    : lastResult.status === "skipped"
                    ? "text-muted-foreground"
                    : "text-loss"
                }`}
                data-testid="mo-last-result"
              >
                {lastResult.message}
                {lastResult.ema_sl?.message && (
                  <span className="block opacity-80 mt-0.5">
                    ↳ {lastResult.ema_sl.message}
                  </span>
                )}
              </div>
            )}
            <Button
              type="submit"
              disabled={busy || connectedBrokers.length === 0}
              data-testid="mo-submit-button"
              className={`rounded-sm h-10 text-sm font-medium px-6 ml-auto ${
                sideIsBuy
                  ? "bg-profit hover:bg-profit/90 text-white"
                  : "bg-loss hover:bg-loss/90 text-white"
              }`}
            >
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Placing...
                </>
              ) : connectedBrokers.length === 0 ? (
                <>No broker connected</>
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  {form.amo ? "Queue AMO " : "Place "}
                  {sideIsBuy ? "BUY" : "SELL"}
                </>
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function SelectField({ label, value, onChange, options, testid, className = "" }) {
  return (
    <div className={`space-y-1.5 ${className}`}>
      <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        {label}
      </Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          data-testid={testid}
          className="h-9 rounded-sm bg-surface-1 border-border text-xs"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function ToggleBlock({ icon: Icon, title, hint, checked, onCheckedChange, disabled, testid }) {
  return (
    <div
      className={`border border-border rounded-sm p-3 bg-surface-1 flex items-start gap-3 transition-opacity ${
        disabled ? "opacity-50" : ""
      }`}
    >
      <Icon className="w-4 h-4 mt-0.5 text-brand shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium leading-tight">{title}</p>
          <Switch
            checked={checked}
            onCheckedChange={onCheckedChange}
            disabled={disabled}
            data-testid={testid}
          />
        </div>
        <p className="text-[10px] text-muted-foreground mt-1 leading-snug">{hint}</p>
      </div>
    </div>
  );
}

function PreviewCell({ label, value, accent = "text-foreground" }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm ${accent}`}>{value}</div>
    </div>
  );
}
