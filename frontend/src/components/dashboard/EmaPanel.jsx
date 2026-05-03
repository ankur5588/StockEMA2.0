import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Siren, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function EmaPanel({ kotakAuthenticated }) {
  const anyAuth = !!kotakAuthenticated; // prop name kept for compat; value is any broker auth
  const [logs, setLogs] = useState([]);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/ema-sl/logs?limit=30");
      setLogs(res.data.logs || []);
    } catch (e) {
      /* noop */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async () => {
    if (!anyAuth) {
      toast.error("Connect at least one broker first");
      return;
    }
    setRunning(true);
    try {
      const res = await api.post("/ema-sl/run");
      toast.success(
        `EMA10 SL run completed — ${res.data.count} position(s) processed`
      );
      setConfirming(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "EMA SL run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm h-full"
      data-testid="ema-panel-card"
    >
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / command
        </div>
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <Zap className="w-4 h-4 text-warn" />
          EMA10 Stoploss
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          Pulls your open positions from Kotak Neo, computes EMA10 on daily
          closes, and places SL orders at the EMA10 trigger for each long
          position.
        </p>

        {!confirming ? (
          <Button
            onClick={() => setConfirming(true)}
            disabled={!anyAuth || running}
            data-testid="ema-run-button"
            className="w-full h-10 rounded-sm bg-warn text-black hover:bg-warn/90 font-medium text-xs uppercase tracking-[0.12em]"
          >
            <Siren className="w-3.5 h-3.5 mr-2" />
            Run EMA10 SL Now
          </Button>
        ) : (
          <div className="space-y-2 border border-warn/50 bg-warn/5 p-3 rounded-sm">
            <div className="text-xs text-warn font-mono uppercase tracking-[0.12em]">
              confirm live action
            </div>
            <p className="text-xs text-muted-foreground">
              This places REAL SL orders on your Kotak Neo account.
            </p>
            <div className="flex gap-2 pt-1">
              <Button
                onClick={run}
                disabled={running}
                data-testid="ema-confirm-button"
                className="flex-1 h-9 rounded-sm bg-warn text-black hover:bg-warn/90 text-xs font-medium"
              >
                {running ? "Running..." : "Yes, execute"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => setConfirming(false)}
                className="h-9 rounded-sm text-xs"
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold mb-2">
            Recent runs
          </div>
          <div className="border border-border rounded-sm divide-y divide-border max-h-[200px] overflow-y-auto">
            {logs.length === 0 ? (
              <div className="py-5 text-center text-xs text-muted-foreground">
                No runs yet.
              </div>
            ) : (
              logs.map((l) => (
                <div
                  key={l.id}
                  className="px-3 py-2 text-xs font-mono flex items-center gap-2"
                  data-testid="ema-log-row"
                >
                  <span className="text-muted-foreground text-[10px]">
                    {new Date(l.created_at).toLocaleTimeString("en-IN", {
                      hour12: false,
                    })}
                  </span>
                  <span className="flex-1 truncate">{l.symbol}</span>
                  <span className="text-muted-foreground">×{l.quantity}</span>
                  <span className="text-warn">
                    EMA10 {l.ema10 ?? "—"}
                  </span>
                  <span
                    className={`text-[10px] uppercase ${
                      l.status === "placed"
                        ? "text-profit"
                        : l.status === "error"
                        ? "text-loss"
                        : "text-muted-foreground"
                    }`}
                  >
                    {l.status}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
