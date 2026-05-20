import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AlertTriangle, RefreshCw, Shield, TrendingDown, Wallet } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const BROKER_LABELS = {
  kotak_neo: "Kotak",
  dhan: "Dhan",
  alice_blue: "Alice",
  indmoney: "INDmoney",
  delta_exchange: "Delta",
};

const inr = (n) => {
  if (n == null) return "—";
  const v = Number(n);
  if (Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

const pct = (n) => {
  if (n == null) return "—";
  const v = Number(n);
  if (Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
};

const riskTone = (p) => {
  if (p == null) return "text-muted-foreground";
  if (p <= 2) return "text-profit";
  if (p <= 5) return "text-warn";
  return "text-loss";
};

export default function PortfolioRiskCard({ anyAuthenticated }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/portfolio/risk");
      setData(res.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load portfolio risk");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (anyAuthenticated) load();
  }, [anyAuthenticated, load]);

  const totals = data?.totals;
  const positions = data?.positions || [];
  const missing = data?.positions_missing_ema || [];

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm"
      data-testid="portfolio-risk-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / risk
          </div>
          <CardTitle className="text-lg font-medium flex items-center gap-2">
            <Shield className="w-4 h-4 text-brand" />
            Portfolio Risk
          </CardTitle>
          <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed max-w-2xl">
            Live exposure across all connected brokers and your downside if every
            position's EMA10 stoploss were to trigger.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading || !anyAuthenticated}
          data-testid="refresh-portfolio-risk-button"
          className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {!anyAuthenticated ? (
          <div className="py-10 text-center text-xs text-muted-foreground border border-dashed border-border rounded-sm">
            Connect at least one broker to compute risk.
          </div>
        ) : !data ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            {loading ? "Loading portfolio..." : "Click Refresh to fetch positions."}
          </div>
        ) : positions.length === 0 && missing.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground border border-dashed border-border rounded-sm">
            No open long positions found.
          </div>
        ) : (
          <>
            {/* Totals row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat
                icon={Wallet}
                label="Current value"
                value={inr(totals.current_value)}
                hint={`${totals.open_positions} position${totals.open_positions !== 1 ? "s" : ""}`}
                testid="kpi-current-value"
              />
              <Stat
                icon={TrendingDown}
                label="If SL hits"
                value={inr(totals.sl_value)}
                hint="∑ qty × EMA10"
                tone="muted"
                testid="kpi-sl-value"
              />
              <Stat
                icon={AlertTriangle}
                label="Risk amount"
                value={inr(totals.risk_amount)}
                hint={pct(totals.risk_pct) + " of book"}
                tone={
                  totals.risk_pct > 5 ? "loss" : totals.risk_pct > 2 ? "warn" : "ok"
                }
                testid="kpi-risk-amount"
              />
              <Stat
                icon={Shield}
                label="Open P&L"
                value={inr(totals.pnl_amount)}
                hint={pct(totals.pnl_pct)}
                tone={totals.pnl_amount > 0 ? "ok" : totals.pnl_amount < 0 ? "loss" : "muted"}
                testid="kpi-pnl"
              />
            </div>

            {/* Risk meter */}
            {totals.current_value > 0 && (
              <div data-testid="risk-meter">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-semibold">
                    Downside if all SLs hit
                  </span>
                  <span className={`text-xs font-mono ${riskTone(totals.risk_pct)}`}>
                    {pct(totals.risk_pct)}
                  </span>
                </div>
                <div className="h-2 bg-surface-1 rounded-sm overflow-hidden border border-border">
                  <div
                    className={`h-full transition-all ${
                      totals.risk_pct > 5
                        ? "bg-loss"
                        : totals.risk_pct > 2
                        ? "bg-warn"
                        : "bg-profit"
                    }`}
                    style={{
                      width: `${Math.min(100, Math.max(0, totals.risk_pct * 5))}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between text-[9px] font-mono text-muted-foreground mt-1">
                  <span>0%</span>
                  <span>5%</span>
                  <span>10%</span>
                  <span>15%</span>
                  <span>20%+</span>
                </div>
              </div>
            )}

            {/* Per-position breakdown */}
            {positions.length > 0 && (
              <div className="border border-border rounded-sm overflow-hidden">
                <Table data-testid="risk-positions-table">
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <Th>Symbol</Th>
                      <Th>Broker</Th>
                      <Th className="text-right">Qty</Th>
                      <Th className="text-right">LTP</Th>
                      <Th className="text-right">EMA10</Th>
                      <Th className="text-right">Value</Th>
                      <Th className="text-right">SL value</Th>
                      <Th className="text-right">Risk</Th>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {positions.map((p, i) => (
                      <TableRow
                        key={`${p.symbol}-${p.broker}-${i}`}
                        className="border-border hover:bg-surface-3"
                        data-testid="risk-position-row"
                      >
                        <TableCell className="font-mono text-xs py-2 px-3">
                          {p.symbol}
                        </TableCell>
                        <TableCell className="text-[10px] py-2 px-3 uppercase tracking-wider text-muted-foreground">
                          {BROKER_LABELS[p.broker] || p.broker}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">
                          {p.quantity}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">
                          {inr(p.mark_price)}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right text-warn">
                          {inr(p.ema10)}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">
                          {inr(p.current_value)}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right text-muted-foreground">
                          {inr(p.sl_value)}
                        </TableCell>
                        <TableCell
                          className={`font-mono text-xs py-2 px-3 text-right ${riskTone(
                            p.risk_pct
                          )}`}
                        >
                          {pct(p.risk_pct)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {missing.length > 0 && (
              <div
                className="border border-warn/40 bg-warn/5 rounded-sm p-3 text-[11px] text-warn flex items-start gap-2"
                data-testid="missing-ema-notice"
              >
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium">EMA10 unavailable</span> for{" "}
                  {missing.length} position{missing.length !== 1 ? "s" : ""} (
                  {missing.map((m) => m.symbol).join(", ")}). They are excluded
                  from the risk total.
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ icon: Icon, label, value, hint, tone = "default", testid }) {
  const valueColor =
    tone === "ok"
      ? "text-profit"
      : tone === "loss"
      ? "text-loss"
      : tone === "warn"
      ? "text-warn"
      : tone === "muted"
      ? "text-muted-foreground"
      : "text-foreground";
  return (
    <div
      className="border border-border bg-surface-1 rounded-sm p-3 space-y-1.5"
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className={`text-lg font-mono ${valueColor}`}>{value}</div>
      {hint && (
        <div className="text-[10px] font-mono text-muted-foreground">{hint}</div>
      )}
    </div>
  );
}

function Th({ children, className = "" }) {
  return (
    <TableHead
      className={`text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold py-2.5 px-3 ${className}`}
    >
      {children}
    </TableHead>
  );
}
