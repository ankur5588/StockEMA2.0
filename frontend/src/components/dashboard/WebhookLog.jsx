import React, { useEffect, useRef, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowDownToLine, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

export default function WebhookLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const listRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/webhooks/logs?limit=30");
      setLogs(res.data.logs || []);
    } catch (e) {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
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
      data-testid="webhook-log-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / signals
          </div>
          <CardTitle className="text-lg font-medium">Webhook Feed</CardTitle>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
          data-testid="refresh-webhook-log-button"
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
            Waiting for Chartink webhooks...
          </div>
        ) : (
          <>
            <div
              ref={listRef}
              className="max-h-[360px] overflow-y-auto divide-y divide-border scroll-smooth"
              data-testid="webhook-log-list"
            >
              {logs.map((l) => (
                <div
                  key={l.id}
                  className="px-3 py-2 text-xs hover:bg-surface-3"
                  data-testid="webhook-log-row"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {new Date(l.created_at).toLocaleTimeString("en-IN", {
                        hour12: false,
                      })}
                    </span>
                    <span className="font-medium truncate">{l.alert_name}</span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                      {l.stocks?.length || 0} stocks
                    </span>
                  </div>
                  {l.stocks?.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1 font-mono">
                      {l.stocks.slice(0, 8).map((s, i) => (
                        <span
                          key={`${s}-${i}`}
                          className="text-[10px] border border-border bg-surface-1 rounded-sm px-1.5 py-0.5"
                        >
                          {s}
                        </span>
                      ))}
                      {l.stocks.length > 8 && (
                        <span className="text-[10px] text-muted-foreground">
                          +{l.stocks.length - 8} more
                        </span>
                      )}
                    </div>
                  )}
                  {l.result_note && (
                    <div className="mt-1 text-[10px] text-muted-foreground truncate">
                      {l.result_note}
                    </div>
                  )}
                </div>
              ))}
            </div>
            {logs.length > 5 && (
              <Button
                type="button"
                size="sm"
                onClick={scrollToBottom}
                data-testid="webhook-log-scroll-bottom-button"
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
