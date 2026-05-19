import React, { useCallback, useEffect, useState } from "react";
import Header from "@/components/layout/Header";
import LiveBanner from "@/components/layout/LiveBanner";
import ConnectionCard from "@/components/dashboard/ConnectionCard";
import DhanCard from "@/components/dashboard/DhanCard";
import AliceBlueCard from "@/components/dashboard/AliceBlueCard";
import INDmoneyCard from "@/components/dashboard/INDmoneyCard";
import WebhookCard from "@/components/dashboard/WebhookCard";
import EmaPanel from "@/components/dashboard/EmaPanel";
import AlertsConfig from "@/components/dashboard/AlertsConfig";
import BacktestPanel from "@/components/dashboard/BacktestPanel";
import PositionsTable from "@/components/dashboard/PositionsTable";
import TradeLog from "@/components/dashboard/TradeLog";
import WebhookLog from "@/components/dashboard/WebhookLog";
import ComplianceCard from "@/components/dashboard/ComplianceCard";
import SymbolMappings from "@/components/dashboard/SymbolMappings";
import ManualOrderCard from "@/components/dashboard/ManualOrderCard";
import PortfolioRiskCard from "@/components/dashboard/PortfolioRiskCard";
import { api } from "@/lib/api";

export default function Dashboard({ user }) {
  const [status, setStatus] = useState(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get("/brokers/status");
      setStatus(res.data);
    } catch (e) {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 30000);
    return () => clearInterval(t);
  }, [loadStatus]);

  // Wrap the Kotak-shape status so the existing Kotak card keeps working.
  const kotakStatus = status
    ? {
        ...(status.kotak_neo || {}),
        webhook_token: status.webhook_token,
        webhook_url: status.webhook_url,
      }
    : null;

  const anyAuth =
    !!status?.kotak_neo?.is_authenticated ||
    !!status?.dhan?.is_authenticated ||
    !!status?.alice_blue?.is_authenticated ||
    !!status?.indmoney?.is_authenticated;

  return (
    <div
      className="min-h-screen bg-surface-1 text-foreground"
      data-testid="dashboard-page"
    >
      <LiveBanner />
      <Header user={user} />

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2 pb-2">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              / control room
            </div>
            <h1 className="text-2xl sm:text-3xl font-medium tracking-tight mt-1">
              Welcome, {user?.name?.split(" ")[0] || "Trader"}
            </h1>
          </div>
          <div className="font-mono text-[10px] text-muted-foreground tracking-wider">
            {new Date().toLocaleString("en-IN", { hour12: false })}
          </div>
        </div>

        {/* Brokers grid */}
        <section data-testid="brokers-section">
          <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-semibold mb-3">
            / brokers
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <ConnectionCard status={kotakStatus} reload={loadStatus} />
            <DhanCard status={status?.dhan} reload={loadStatus} />
            <AliceBlueCard status={status?.alice_blue} reload={loadStatus} />
            <INDmoneyCard status={status?.indmoney} reload={loadStatus} />
          </div>
        </section>

        {/* Ops row */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <WebhookCard status={kotakStatus} />
          <EmaPanel kotakAuthenticated={anyAuth} />
          <ComplianceCard />
        </div>

        {/* Positions + Alerts */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <PositionsTable anyAuthenticated={anyAuth} />
          </div>
          <AlertsConfig />
        </div>

        {/* Portfolio Risk (full-width) */}
        <PortfolioRiskCard anyAuthenticated={anyAuth} />

        {/* Manual Order */}
        <ManualOrderCard brokersStatus={status} reload={loadStatus} />

        {/* Symbol Mappings (full-width) */}
        <SymbolMappings />

        {/* Backtest (full-width) */}
        <BacktestPanel />

        {/* Logs */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <WebhookLog />
          <TradeLog />
        </div>

        <footer className="pt-4 pb-8 text-[10px] font-mono text-muted-foreground tracking-wider flex items-center justify-between">
          <span>
            chartink-trade · v1.1 ·{" "}
            <span className="text-brand">multi-broker</span>
          </span>
          <span>NSE / BSE · live-trading</span>
        </footer>
      </main>
    </div>
  );
}
