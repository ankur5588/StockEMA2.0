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
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function PositionsTable({ anyAuthenticated }) {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!anyAuthenticated) {
      setPositions([]);
      return;
    }
    setLoading(true);
    try {
      const res = await api.get("/positions/all");
      setPositions(res.data.positions || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [anyAuthenticated]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm h-full"
      data-testid="positions-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / book
          </div>
          <CardTitle className="text-lg font-medium">Open Positions</CardTitle>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading || !anyAuthenticated}
          data-testid="refresh-positions-button"
          className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {!anyAuthenticated ? (
          <EmptyState text="Connect at least one broker to view open positions." />
        ) : positions.length === 0 ? (
          <EmptyState text={loading ? "Loading..." : "No open positions."} />
        ) : (
          <Table data-testid="positions-table">
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <Th>Symbol</Th>
                <Th>Broker</Th>
                <Th className="text-right">Qty</Th>
                <Th className="text-right">Avg Price</Th>
                <Th className="text-right">LTP</Th>
                <Th className="text-right">P&amp;L</Th>
                <Th>Product</Th>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p, i) => (
                <TableRow
                  key={`${p.symbol}-${p.broker}-${i}`}
                  className="border-border hover:bg-surface-3"
                  data-testid="position-row"
                >
                  <TableCell className="font-mono text-xs py-2.5 px-3">
                    {p.symbol}
                  </TableCell>
                  <TableCell className="text-[10px] py-2.5 px-3 uppercase tracking-wider text-muted-foreground">
                    {brokerLabel(p.broker)}
                  </TableCell>
                  <TableCell className="font-mono text-xs py-2.5 px-3 text-right">
                    {p.quantity}
                  </TableCell>
                  <TableCell className="font-mono text-xs py-2.5 px-3 text-right">
                    {p.avg_price?.toFixed?.(2) ?? p.avg_price}
                  </TableCell>
                  <TableCell className="font-mono text-xs py-2.5 px-3 text-right">
                    {p.ltp == null ? "—" : p.ltp.toFixed(2)}
                  </TableCell>
                  <TableCell
                    className={`font-mono text-xs py-2.5 px-3 text-right ${
                      (p.pnl ?? 0) > 0
                        ? "text-profit"
                        : (p.pnl ?? 0) < 0
                        ? "text-loss"
                        : ""
                    }`}
                  >
                    {p.pnl == null ? "—" : p.pnl.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-xs py-2.5 px-3 text-muted-foreground">
                    {p.product || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function brokerLabel(b) {
  if (b === "kotak_neo") return "Kotak";
  if (b === "dhan") return "Dhan";
  if (b === "alice_blue") return "Alice";
  return b || "—";
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

function EmptyState({ text }) {
  return (
    <div className="py-10 text-center text-xs text-muted-foreground">{text}</div>
  );
}
