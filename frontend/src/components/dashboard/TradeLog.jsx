import React, { useEffect, useRef, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowDownToLine, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

export default function TradeLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const listRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/trades/logs?limit=50");
      setLogs(res.data.logs || []);
    } catch (e) {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const scrollToBottom = () => {
    if (listRef.current) {
      listRef.current.scrollTo({
        top: listRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  };

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm h-full"
      data-testid="trade-log-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / tape
          </div>
          <CardTitle className="text-lg font-medium">Trade Log</CardTitle>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
          data-testid="refresh-trade-log-button"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="p-0 relative">
        {logs.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            No trades yet.
          </div>
        ) : (
          <>
            <div
              ref={listRef}
              className="max-h-[360px] overflow-y-auto divide-y divide-border scroll-smooth"
              data-testid="trade-log-list"
            >
              {logs.map((l) => (
                <LogRow key={l.id} log={l} />
              ))}
            </div>
            {logs.length > 5 && (
              <Button
                type="button"
                size="sm"
                onClick={scrollToBottom}
                data-testid="trade-log-scroll-bottom-button"
                className="absolute bottom-2 right-2 h-7 w-7 p-0 rounded-full bg-surface-3 hover:bg-brand text-foreground border border-border shadow-md"
                title="Scroll to oldest"
              >
                <ArrowDownToLine className="w-3.5 h-3.5" />
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function LogRow({ log }) {
  const time = new Date(log.created_at).toLocaleTimeString("en-IN", {
    hour12: false,
  });
  const statusColor =
    log.status === "success" || log.status === "placed"
      ? "text-profit"
      : log.status === "error"
      ? "text-loss"
      : "text-warn";
  return (
    <div
      className="px-3 py-2 text-xs font-mono flex items-center gap-3 hover:bg-surface-3"
      data-testid="trade-log-row"
    >
      <span className="text-muted-foreground shrink-0">{time}</span>
      <span
        className={`uppercase shrink-0 text-[10px] tracking-wider ${
          log.transaction_type === "B" ? "text-profit" : "text-loss"
        }`}
      >
        {log.transaction_type === "B" ? "BUY" : "SELL"}
      </span>
      <span className="shrink-0 w-24 truncate">{log.symbol}</span>
      <span className="shrink-0 text-muted-foreground">×{log.quantity}</span>
      <span className="shrink-0 text-[10px] uppercase text-muted-foreground tracking-wider">
        [{log.source}]
      </span>
      <span className={`shrink-0 text-[10px] uppercase ${statusColor}`}>
        {log.status}
      </span>
      <span className="truncate text-muted-foreground flex-1">
        {log.message}
      </span>
    </div>
  );
}
