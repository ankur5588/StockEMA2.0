import React, { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const KIND_STYLE = {
  kill: "text-loss",
  alert: "text-warn",
  turned_negative: "text-loss",
  rearmed: "text-profit",
  baseline: "text-muted-foreground",
  data_unavailable: "text-muted-foreground",
};

export default function RegimeCard() {
  const [data, setData] = useState(null);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([
        api.get("/regime/status"),
        api.get("/regime/events?limit=8"),
      ]);
      setData(s.data);
      setEvents(e.data.events || []);
    } catch (err) {
      /* ignore: card shows empty state */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const st = data?.settings || {};
  const cur = data?.current;
  const negative = cur?.signal === "negative";

  const save = async (patch, extra = {}) => {
    setBusy(true);
    try {
      await api.post("/regime/settings", {
        enabled: !!st.enabled,
        mode: st.mode || "alert",
        block_buys: st.block_buys !== false,
        ...patch,
        ...extra,
      });
      await load();
      toast.success("Saved");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const goLive = () => {
    if (
      !window.confirm(
        "LIVE mode will cancel your stoploss orders and SELL your whole portfolio at market " +
          "price when Nifty's 20-day average falls below its 50-day average. It does not sell " +
          "if the signal is already negative now. Turn on Live mode?"
      )
    )
      return;
    save({ mode: "live", enabled: true }, { confirm_live: true });
  };

  return (
    <Card className="bg-surface-2 border-border rounded-sm" data-testid="regime-card">
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / portfolio protection
        </div>
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-warn" />
          Market kill switch
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          Watches Nifty 50 every weekday at 9:20 AM IST. When its 20-day average
          falls below its 50-day average, it can sell everything and block new buys until
          the signal turns positive again.
        </p>

        <div className="grid grid-cols-3 gap-2 text-center">
          <Stat label="Signal" value={cur ? (negative ? "NEGATIVE" : "positive") : "\u2014"}
                tone={cur ? (negative ? "bad" : "ok") : "n"} />
          <Stat label="20-day avg" value={cur?.sma20 ?? "\u2014"} />
          <Stat label="50-day avg" value={cur?.sma50 ?? "\u2014"} />
        </div>

        <Row label="Watch the market" hint="Records alerts. Sells nothing in Alert mode.">
          <Switch checked={!!st.enabled} disabled={busy}
                  onCheckedChange={(v) => save({ enabled: v })}
                  data-testid="regime-enabled" />
        </Row>
        <Row label="Block new buys while negative" hint="Webhook and manual buys are refused.">
          <Switch checked={st.block_buys !== false} disabled={busy}
                  onCheckedChange={(v) => save({ block_buys: v })}
                  data-testid="regime-block-buys" />
        </Row>
        <Row
          label={`Mode: ${st.mode === "live" ? "LIVE (sells)" : "Alert only"}`}
          hint="Live sells your portfolio once, when the signal turns negative."
        >
          {st.mode === "live" ? (
            <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => save({ mode: "alert" })}
                    className="rounded-sm h-8 text-xs" data-testid="regime-to-alert">
              Back to Alert
            </Button>
          ) : (
            <Button size="sm" disabled={busy} onClick={goLive}
                    className="rounded-sm h-8 text-xs bg-loss text-white hover:bg-loss/90"
                    data-testid="regime-to-live">
              Go Live
            </Button>
          )}
        </Row>

        {st.enabled && st.last_signal === "negative" && st.block_buys !== false && (
          <div className="text-[11px] text-warn border border-warn/40 bg-warn/5 rounded-sm p-2">
            Signal is negative: new buys are blocked.
          </div>
        )}

        <div className="border border-border rounded-sm divide-y divide-border">
          {events.length === 0 ? (
            <div className="p-3 text-[11px] text-muted-foreground">No events yet</div>
          ) : (
            events.map((e, i) => (
              <div key={i} className="px-3 py-2 text-[11px] font-mono" data-testid="regime-event">
                <span className="text-muted-foreground mr-2">
                  {new Date(e.created_at).toLocaleString("en-IN", { hour12: false })}
                </span>
                <span className={KIND_STYLE[e.kind] || ""}>{e.message}</span>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <div className="text-xs text-white">{label}</div>
        <div className="text-[10px] text-muted-foreground">{hint}</div>
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, tone = "n" }) {
  const color = tone === "ok" ? "text-profit" : tone === "bad" ? "text-loss" : "text-white";
  return (
    <div className="border border-border p-2 bg-surface-1 rounded-sm">
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-sm ${color}`}>{value}</div>
    </div>
  );
}
