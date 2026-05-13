import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Check, Copy, Webhook } from "lucide-react";
import { toast } from "sonner";

export default function WebhookCard({ status }) {
  const url = status?.webhook_url;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Webhook URL copied");
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      toast.error("Copy failed");
    }
  };

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm h-full"
      data-testid="webhook-card"
    >
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / ingress
        </div>
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <Webhook className="w-4 h-4 text-brand" />
          Chartink Webhook
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!url ? (
          <div className="border border-dashed border-border p-4 rounded-sm text-xs text-muted-foreground">
            Save Kotak credentials to generate your unique webhook URL.
          </div>
        ) : (
          <>
            <div
              className="group border border-border bg-surface-1 rounded-sm p-3 flex items-center gap-2 overflow-x-auto"
              data-testid="webhook-url-box"
            >
              <span className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold shrink-0">
                POST
              </span>
              <code className="font-mono text-[11px] text-white whitespace-nowrap flex-1">
                {url}
              </code>
              <Button
                size="sm"
                variant="ghost"
                onClick={copy}
                data-testid="copy-webhook-button"
                className="h-7 w-7 p-0 rounded-sm"
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5 text-profit" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </Button>
            </div>
            <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                How to wire it
              </div>
              <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside leading-relaxed">
                <li>Open your Chartink scan → Create Alert</li>
                <li>
                  Under <span className="text-white">Webhook URL</span> paste
                  the link above
                </li>
                <li>
                  Make sure an Alert Config below matches the alert name
                </li>
              </ol>
            </div>
            <div
              className="border border-brand/30 bg-brand/5 rounded-sm p-3 space-y-1"
              data-testid="auto-side-banner"
            >
              <div className="text-[10px] uppercase tracking-[0.15em] text-brand font-semibold">
                Auto side-detection
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                If your alert name contains <span className="font-mono text-profit">BUY</span> we place a buy order.
                If it contains <span className="font-mono text-loss">SELL</span> we place a sell order.
                This overrides the alert config and per-symbol mapping side.
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
