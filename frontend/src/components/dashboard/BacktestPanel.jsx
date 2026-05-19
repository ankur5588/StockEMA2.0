import React, { useState, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Play, CheckCircle2, XCircle, BarChart3, Upload, Download,
  TrendingUp, PieChart,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const CRITERIA_LABELS = {
  range_expansion_7d: "Range expansion 7d",
  close_gt_open: "Close > Open",
  close_gt_prev_close: "Close > Prev close",
  weekly_close_gt_open: "Weekly close > open",
  monthly_close_gt_open: "Monthly close > open",
  volume_gt_500k: "Volume > 500K",
  sma_20_gt_50: "SMA(20) > SMA(50)",
  sma_50_gt_200: "SMA(50) > SMA(200)",
  rsi_gt_50: "RSI(14) > 50",
};

const PERIODS = [
  { value: "6mo", label: "6 months" },
  { value: "1y", label: "1 year" },
  { value: "2y", label: "2 years" },
];

export default function BacktestPanel() {
  const [mode, setMode] = useState("scan"); // "scan" | "signals"
  const [symbols, setSymbols] = useState("");
  const [period, setPeriod] = useState("1y");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [expandedRow, setExpandedRow] = useState(null);
  const [showBreakdown, setShowBreakdown] = useState(false);
  const fileRef = useRef(null);

  // Scan mode
  const runScan = async () => {
    setRunning(true);
    setResult(null);
    try {
      const params = { period };
      if (symbols.trim()) params.symbols = symbols.trim();
      const res = await api.post("/backtest/run", null, { params });
      setResult(res.data);
      toast.success(`Scan complete — ${res.data.passed} / ${res.data.data_available} passed`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Scan failed");
    } finally {
      setRunning(false);
    }
  };

  // Signal backtest from CSV
  const uploadSignals = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setRunning(true);
    setResult(null);
    try {
      const text = await file.text();
      const res = await api.post("/backtest/signals", text, {
        headers: { "Content-Type": "text/csv" },
      });
      setResult(res.data);
      const { passed, data_available, errors } = res.data;
      let msg = `Evaluated ${data_available} signals — ${passed} passed`;
      if (errors?.length) msg += `, ${errors.length} parse errors`;
      toast.success(msg);
      if (errors?.length) {
        errors.slice(0, 3).forEach((er) => toast.error(er));
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (detail?.errors?.length) {
        toast.error(`CSV invalid: ${detail.errors[0]}`);
      } else {
        toast.error(detail || "Upload failed");
      }
    } finally {
      setRunning(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const downloadTemplate = () => {
    const sample =
      "date,symbol,marketcapname,sector\n" +
      "2025-05-15,RELIANCE,Largecap,Energy\n" +
      "2025-05-15,TCS,Largecap,I.T\n" +
      "2025-05-16,INFY,Largecap,I.T\n";
    try {
      const blob = new Blob([sample], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "backtest_signals_template.csv";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 100);
      toast.success("Template downloaded");
    } catch (err) {
      toast.error(err?.message || "Download failed");
    }
  };

  const hasSector = result?.results?.some((r) => r.sector);
  const hasMarketcap = result?.results?.some((r) => r.marketcapname);

  return (
    <Card className="bg-surface-2 border-border rounded-sm" data-testid="backtest-card">
      <CardHeader className="pb-3">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
          / analysis
        </div>
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-brand" />
          Screening Backtest
        </CardTitle>
        <p className="text-[11px] text-muted-foreground mt-1 max-w-2xl leading-relaxed">
          Evaluate the momentum screening criteria (range expansion, SMA order, RSI &gt; 50,
          volume &gt; 500K, etc.) against a universe of stocks or your own signal CSV.
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Mode tabs */}
        <div className="flex gap-1 border border-border rounded-sm p-0.5 w-fit">
          <button
            onClick={() => { setMode("scan"); setResult(null); }}
            className={`px-3 py-1.5 text-xs rounded-sm font-medium transition-colors ${
              mode === "scan"
                ? "bg-brand text-white"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <TrendingUp className="w-3 h-3 mr-1.5 inline-block" />
            Scan Universe
          </button>
          <button
            onClick={() => { setMode("signals"); setResult(null); }}
            className={`px-3 py-1.5 text-xs rounded-sm font-medium transition-colors ${
              mode === "signals"
                ? "bg-brand text-white"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Upload className="w-3 h-3 mr-1.5 inline-block" />
            Signal CSV
          </button>
        </div>

        {/* Controls */}
        {mode === "scan" ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Symbols (comma-separated, empty = NIFTY 100)
              </Label>
              <Input value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                placeholder="RELIANCE,TCS,INFY (leave empty for NIFTY 100)"
                data-testid="backtest-symbols-input"
                className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Period
              </Label>
              <div className="flex gap-2">
                <Select value={period} onValueChange={setPeriod}>
                  <SelectTrigger data-testid="backtest-period-select"
                    className="h-9 rounded-sm bg-surface-1 border-border text-xs flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PERIODS.map((p) => (
                      <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button onClick={runScan} disabled={running}
                  data-testid="backtest-run-button"
                  className="h-9 rounded-sm text-xs bg-brand hover:bg-brand/90 text-white px-4">
                  <Play className="w-3.5 h-3.5 mr-1.5" />
                  {running ? "Scanning..." : "Run"}
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2 items-end">
            <div className="space-y-1.5 flex-1 min-w-[200px]">
              <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                Upload signals CSV (date,symbol,marketcapname,sector)
              </Label>
              <div className="flex gap-2">
                <input ref={fileRef} type="file" accept=".csv,text/csv"
                  onChange={uploadSignals} className="hidden" data-testid="signals-csv-input" />
                <Button size="sm" variant="outline" onClick={downloadTemplate}
                  className="rounded-sm h-9 text-xs border-border bg-surface-1 hover:bg-surface-3">
                  <Download className="w-3.5 h-3.5 mr-1.5" />
                  Template
                </Button>
                <Button size="sm" onClick={() => fileRef.current?.click()} disabled={running}
                  data-testid="signals-upload-button"
                  className="rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white">
                  <Upload className="w-3.5 h-3.5 mr-1.5" />
                  {running ? "Processing..." : "Upload CSV"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Summary */}
        {result && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <SummaryCard label={mode === "signals" ? "Signals" : "Scanned"} value={result.total_scanned} />
            <SummaryCard label="Data available" value={result.data_available} />
            <SummaryCard label="Passed" value={result.passed} color="text-profit" />
            <SummaryCard label="Failed" value={result.failed} color="text-loss" />
            <SummaryCard label="Pass rate" value={`${result.pass_rate}%`} />
          </div>
        )}

        {/* Portfolio allocation */}
        {result?.portfolio?.allocation && Object.keys(result.portfolio.allocation).length > 0 && (
          <div className="border border-border rounded-sm p-3 space-y-2">
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              Portfolio Allocation (₹{result.portfolio.total_capital?.toLocaleString("en-IN")} capital)
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {Object.entries(result.portfolio.allocation).map(([cap, data]) => (
                <div key={cap} className="border border-border rounded-sm px-3 py-2">
                  <div className={`text-[11px] uppercase tracking-wider font-semibold ${
                    cap === "Largecap" ? "text-brand" : cap === "Midcap" ? "text-warn" : "text-muted-foreground"
                  }`}>{cap}</div>
                  <div className="text-2xl font-mono font-medium mt-0.5">{data.allocation_pct}%</div>
                  <div className="text-xs text-muted-foreground font-mono">
                    ₹{data.capital_amount?.toLocaleString("en-IN")} · {data.signals_passed}/{data.signals_total} passed
                  </div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <div className="text-center">
                <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Avg open positions</div>
                <div className="text-lg font-mono font-medium">{result.portfolio.avg_open_positions}</div>
              </div>
              <div className="text-center">
                <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Max open positions</div>
                <div className="text-lg font-mono font-medium text-warn">{result.portfolio.max_open_positions}</div>
              </div>
              <div className="text-center">
                <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Per trade capital</div>
                <div className="text-lg font-mono font-medium text-profit">₹{result.portfolio.per_trade_capital?.toLocaleString("en-IN")}</div>
              </div>
              <div className="text-center">
                <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Trading days</div>
                <div className="text-lg font-mono font-medium">{result.portfolio.trading_days_with_signals}</div>
              </div>
            </div>
          </div>
        )}

        {/* Forward returns / win rate */}
        {result?.returns && Object.keys(result.returns).length > 0 && (
          <div className="border border-border rounded-sm p-3 space-y-2">
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              Returns &amp; Win Rate (buy at signal close, sell at horizon)
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(result.returns).map(([horizon, data]) => (
                <div key={horizon} className="border border-border rounded-sm px-3 py-2 text-center">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{horizon}</div>
                  <div className={`text-lg font-mono font-medium mt-0.5 ${data.win_rate >= 60 ? "text-profit" : data.win_rate >= 40 ? "text-warn" : "text-loss"}`}>
                    {data.win_rate}%
                  </div>
                  <div className="text-[10px] text-muted-foreground">win rate</div>
                  <div className={`text-xs font-mono mt-1 ${data.avg_return > 0 ? "text-profit" : "text-loss"}`}>
                    avg {data.avg_return > 0 ? "+" : ""}{data.avg_return}%
                  </div>
                  {data.count > 0 && (
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      {data.total_wins}W/{data.total_losses}L · {data.count} trades
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Breakdown by sector / marketcap */}
        {result && mode === "signals" && (result.sector_breakdown || result.marketcap_breakdown) && (
          <div>
            <button
              onClick={() => setShowBreakdown(!showBreakdown)}
              className="flex items-center gap-2 text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold hover:text-foreground transition-colors"
            >
              <PieChart className="w-3 h-3" />
              {showBreakdown ? "Hide" : "Show"} breakdown by sector &amp; market cap
            </button>
            {showBreakdown && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
                {result.sector_breakdown && (
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold mb-1">By Sector</div>
                    <div className="border border-border rounded-sm divide-y divide-border max-h-[200px] overflow-y-auto">
                      {Object.entries(result.sector_breakdown).sort((a, b) => b[1].total - a[1].total).map(([sec, data]) => (
                        <div key={sec} className="flex items-center justify-between px-3 py-1.5 text-xs font-mono">
                          <span className="text-muted-foreground truncate">{sec || "(blank)"}</span>
                          <span className="text-foreground">{data.passed}/{data.total}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {result.marketcap_breakdown && (
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold mb-1">By Market Cap</div>
                    <div className="border border-border rounded-sm divide-y divide-border max-h-[200px] overflow-y-auto">
                      {Object.entries(result.marketcap_breakdown).sort((a, b) => b[1].total - a[1].total).map(([cap, data]) => (
                        <div key={cap} className="flex items-center justify-between px-3 py-1.5 text-xs font-mono">
                          <span className="text-muted-foreground">{cap || "(blank)"}</span>
                          <span className="text-foreground">{data.passed}/{data.total}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Results table */}
        {result && result.results?.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold mb-2">
              Results ({result.passed} passed, {result.failed} failed)
            </div>
            <div className="border border-border rounded-sm overflow-x-auto max-h-[600px] overflow-y-auto">
              <Table data-testid="backtest-results-table">
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    {hasMarketcap && <Th>Cap</Th>}
                    {hasSector && <Th>Sector</Th>}
                    <Th>Date</Th>
                    <Th>Symbol</Th>
                    <Th className="text-right">LTP</Th>
                    <Th className="text-right">1D%</Th>
                    <Th className="text-right">Vol</Th>
                    <Th className="text-right">SMA20</Th>
                    <Th className="text-right">SMA50</Th>
                    <Th className="text-right">SMA200</Th>
                    <Th className="text-right">RSI</Th>
                    <Th className="text-center">Status</Th>
                    <Th />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.results.map((r, i) => (
                    <React.Fragment key={`${r.symbol}-${r.date || i}`}>
                      <TableRow
                        className="border-border hover:bg-surface-3 cursor-pointer"
                        onClick={() => setExpandedRow(expandedRow === i ? null : i)}
                        data-testid="backtest-row"
                      >
                        {hasMarketcap && (
                          <TableCell className="py-2 px-3">
                            {r.marketcapname ? (
                              <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${
                                r.marketcapname === "Largecap" ? "border-brand/30 text-brand bg-brand/10" :
                                r.marketcapname === "Midcap" ? "border-warn/30 text-warn bg-warn/10" :
                                "border-muted-foreground/30 text-muted-foreground bg-muted-foreground/10"
                              }`}>
                                {r.marketcapname}
                              </span>
                            ) : "\u2014"}
                          </TableCell>
                        )}
                        {hasSector && (
                          <TableCell className="text-[10px] text-muted-foreground py-2 px-3 max-w-[100px] truncate">
                            {r.sector || "\u2014"}
                          </TableCell>
                        )}
                        <TableCell className="font-mono text-[10px] text-muted-foreground py-2 px-3">{r.date || "\u2014"}</TableCell>
                        <TableCell className="font-mono text-xs font-medium py-2 px-3">{r.symbol}</TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">{r.ltp ?? "\u2014"}</TableCell>
                        <TableCell className={`font-mono text-xs py-2 px-3 text-right ${(r.change_1d_pct || 0) >= 0 ? "text-profit" : "text-loss"}`}>
                          {r.change_1d_pct != null ? `${r.change_1d_pct >= 0 ? "+" : ""}${r.change_1d_pct}%` : "\u2014"}
                        </TableCell>
                        <TableCell className="font-mono text-[10px] py-2 px-3 text-right">
                          {r.volume != null ? r.volume.toLocaleString("en-IN") : "\u2014"}
                        </TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">{r.sma20 ?? "\u2014"}</TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">{r.sma50 ?? "\u2014"}</TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">{r.sma200 ?? "\u2014"}</TableCell>
                        <TableCell className="font-mono text-xs py-2 px-3 text-right">{r.rsi14 ?? "\u2014"}</TableCell>
                        <TableCell className="py-2 px-3 text-center">
                          {r.passed ? (
                            <CheckCircle2 className="w-4 h-4 text-profit mx-auto" />
                          ) : (
                            <XCircle className="w-4 h-4 text-loss/60 mx-auto" />
                          )}
                        </TableCell>
                        <TableCell className="py-2 px-3 text-center">
                          <span className="text-[10px] text-muted-foreground">
                            {expandedRow === i ? "\u25B2" : "\u25BC"}
                          </span>
                        </TableCell>
                      </TableRow>
                      {expandedRow === i && (
                        <TableRow className="border-border bg-surface-3/50">
                          <TableCell colSpan={13} className="px-4 py-3">
                            <div className="grid grid-cols-3 sm:grid-cols-5 gap-1.5">
                              {Object.entries(CRITERIA_LABELS).map(([key, label]) => (
                                <div key={key} className="flex items-center gap-1.5">
                                  {r.criteria?.[key] ? (
                                    <CheckCircle2 className="w-3 h-3 text-profit shrink-0" />
                                  ) : (
                                    <XCircle className="w-3 h-3 text-loss/60 shrink-0" />
                                  )}
                                  <span className="text-[10px] font-mono text-muted-foreground">{label}</span>
                                </div>
                              ))}
                            </div>
                            {r.error && (
                              <div className="text-[10px] text-loss mt-2 font-mono">{r.error}</div>
                            )}
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {result && result.results?.length === 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground border border-dashed border-border rounded-sm">
            No data available for the scanned symbols.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryCard({ label, value, color = "text-foreground" }) {
  return (
    <div className="border border-border rounded-sm px-3 py-2.5 text-center">
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold">{label}</div>
      <div className={`text-xl font-mono font-medium mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}

function Th({ children, className = "" }) {
  return (
    <TableHead className={`text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold py-2.5 px-3 ${className}`}>
      {children}
    </TableHead>
  );
}
