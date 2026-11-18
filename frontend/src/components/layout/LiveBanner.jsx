import React from "react";
import { AlertTriangle } from "lucide-react";

export default function LiveBanner() {
  return (
    <div
      className="bg-warn text-black border-b border-warn/60"
      data-testid="live-banner"
    >
      <div className="max-w-[1600px] mx-auto px-6 h-9 flex items-center gap-2 text-xs font-medium">
        <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.4} />
        <span className="uppercase tracking-[0.12em] font-mono text-[11px]">
          LIVE TRADING
        </span>
        <span className="text-black/80">
          · Orders placed via webhooks and stoploss runs hit your real Dhan
          account.
        </span>
      </div>
    </div>
  );
}
