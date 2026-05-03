import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Copy, Check, ShieldCheck, ShieldAlert, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function ComplianceCard() {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/deployment/info");
      setInfo(res.data);
    } catch (e) {
      /* noop */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const copy = async () => {
    if (!info?.outbound_ip) return;
    await navigator.clipboard.writeText(info.outbound_ip);
    setCopied(true);
    toast.success("IP copied");
    setTimeout(() => setCopied(false), 1500);
  };

  const isStatic = !!info?.is_static_ip;
  const Icon = isStatic ? ShieldCheck : ShieldAlert;
  const tone = isStatic ? "text-profit" : "text-warn";
  const border = isStatic ? "border-profit/40" : "border-warn/40";

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm"
      data-testid="compliance-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / compliance
          </div>
          <CardTitle className="text-lg font-medium flex items-center gap-2">
            <Icon className={`w-4 h-4 ${tone}`} />
            SEBI / Static IP
          </CardTitle>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={load}
          disabled={loading}
          data-testid="refresh-compliance-button"
          className="h-7 w-7 p-0 rounded-sm"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
          />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          className={`border ${border} bg-surface-1 rounded-sm p-3 space-y-2`}
          data-testid="compliance-ip-box"
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Outbound IP
            </span>
            <code className="font-mono text-sm" data-testid="outbound-ip">
              {info?.outbound_ip || (loading ? "detecting..." : "—")}
            </code>
            {info?.outbound_ip && (
              <Button
                size="sm"
                variant="ghost"
                onClick={copy}
                data-testid="copy-ip-button"
                className="h-6 w-6 p-0 rounded-sm ml-auto"
              >
                {copied ? (
                  <Check className="w-3 h-3 text-profit" />
                ) : (
                  <Copy className="w-3 h-3" />
                )}
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Platform
            </span>
            <span className="font-mono text-xs">
              {info?.platform || "—"}
            </span>
            <span
              className={`ml-auto font-mono text-[10px] px-2 py-0.5 rounded-sm border ${
                isStatic
                  ? "border-profit/40 text-profit bg-profit/10"
                  : "border-warn/40 text-warn bg-warn/10"
              }`}
              data-testid="static-ip-badge"
            >
              {isStatic ? "STATIC IP" : "POOLED IP"}
            </span>
          </div>
        </div>

        {!isStatic ? (
          <div
            className="border border-warn/40 bg-warn/5 rounded-sm p-3 space-y-1.5"
            data-testid="sebi-warning"
          >
            <div className="text-[10px] uppercase tracking-[0.15em] text-warn font-semibold">
              SEBI algo-trading notice
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              This deployment uses a pooled outbound IP. To comply with SEBI
              algo-trading rules, self-host on a VPS with a reserved static IP
              (DigitalOcean Reserved IP, AWS Elastic IP, Linode, Hetzner), then
              whitelist it with Kotak Neo. See <code className="text-white">README.md</code>.
            </p>
          </div>
        ) : (
          <div
            className="border border-profit/40 bg-profit/5 rounded-sm p-3"
            data-testid="sebi-ok"
          >
            <p className="text-xs text-muted-foreground leading-relaxed">
              <span className="text-profit font-medium">Static IP detected.</span>{" "}
              Whitelist the IP above with Kotak Neo and register per SEBI
              algo-trading requirements.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
