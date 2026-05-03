import React, { useCallback, useEffect, useState } from "react";
import Header from "@/components/layout/Header";
import LiveBanner from "@/components/layout/LiveBanner";
import ConnectionCard from "@/components/dashboard/ConnectionCard";
import WebhookCard from "@/components/dashboard/WebhookCard";
import EmaPanel from "@/components/dashboard/EmaPanel";
import AlertsConfig from "@/components/dashboard/AlertsConfig";
import PositionsTable from "@/components/dashboard/PositionsTable";
import TradeLog from "@/components/dashboard/TradeLog";
import WebhookLog from "@/components/dashboard/WebhookLog";
import ComplianceCard from "@/components/dashboard/ComplianceCard";
import { api } from "@/lib/api";

export default function Dashboard({ user }) {
  const [status, setStatus] = useState(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get("/kotak/status");
      setStatus(res.data);
    } catch (e) {
      setStatus({ has_credentials: false, is_authenticated: false });
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 30000);
    return () => clearInterval(t);
  }, [loadStatus]);

  const authenticated = !!status?.is_authenticated;

  return (
    <div
      className="min-h-screen bg-surface-1 text-foreground"
      data-testid="dashboard-page"
    >
      <LiveBanner />
      <Header user={user} />

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-5">
        {/* Page title */}
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

        {/* Row 1: Connection + Webhook + EMA */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <ConnectionCard status={status} reload={loadStatus} />
          <WebhookCard status={status} />
          <EmaPanel kotakAuthenticated={authenticated} />
        </div>

        {/* Row 2: Positions (span 2) + Alerts */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <PositionsTable kotakAuthenticated={authenticated} />
          </div>
          <AlertsConfig />
        </div>

        {/* Row 3: Logs */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <WebhookLog />
          <TradeLog />
        </div>

        {/* Row 4: Compliance */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <ComplianceCard />
        </div>

        <footer className="pt-4 pb-8 text-[10px] font-mono text-muted-foreground tracking-wider flex items-center justify-between">
          <span>
            chartink-trade · v1.0 ·{" "}
            <span className="text-brand">emergent</span>
          </span>
          <span>NSE / BSE · live-trading</span>
        </footer>
      </main>
    </div>
  );
}
