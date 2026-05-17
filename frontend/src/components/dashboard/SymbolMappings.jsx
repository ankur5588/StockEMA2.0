import React, { useEffect, useState, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Plus, Trash2, Upload, Download, Trash } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const BROKERS = [
  { value: "*", label: "Any" },
  { value: "kotak_neo", label: "Kotak" },
  { value: "dhan", label: "Dhan" },
  { value: "alice_blue", label: "Alice" },
  { value: "indmoney", label: "INDmoney" },
];

const blank = {
  chartink_symbol: "",
  nse_symbol: "",
  quantity: "",
  amount: "",
  broker: "*",
  transaction_type: "B",
  product: "CNC",
};

export default function SymbolMappings() {
  const [mappings, setMappings] = useState([]);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/symbol-mappings");
      setMappings(res.data.mappings || []);
    } catch (e) {
      toast.error("Failed to load mappings");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const add = async (e) => {
    e.preventDefault();
    if (!form.chartink_symbol.trim() || !form.nse_symbol.trim()) {
      toast.error("Chartink and NSE symbols are required");
      return;
    }
    if (!form.quantity && !form.amount) {
      toast.error("Provide quantity OR amount");
      return;
    }
    setBusy(true);
    try {
      await api.post("/symbol-mappings", {
        ...form,
        quantity: form.quantity ? Number(form.quantity) : null,
        amount: form.amount ? Number(form.amount) : null,
      });
      toast.success("Mapping saved");
      setForm(blank);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/symbol-mappings/${id}`);
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  const wipeAll = async () => {
    if (!window.confirm("Delete ALL symbol mappings?")) return;
    try {
      const res = await api.delete("/symbol-mappings");
      toast.success(`Deleted ${res.data.deleted} mapping(s)`);
      load();
    } catch (err) {
      toast.error("Failed to clear");
    }
  };

  const upload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      const res = await api.post("/symbol-mappings/upload", text, {
        headers: { "Content-Type": "text/csv" },
      });
      const { inserted, replaced, errors } = res.data;
      let msg = `Imported ${inserted} row(s)`;
      if (replaced) msg += `, replaced ${replaced}`;
      if (errors?.length) msg += ` — ${errors.length} skipped`;
      toast.success(msg);
      if (errors?.length) {
        errors.slice(0, 3).forEach((er) => toast.error(er));
      }
      load();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (detail?.errors?.length) {
        toast.error(`CSV invalid: ${detail.errors[0]}`);
      } else {
        toast.error(detail || "Upload failed");
      }
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const downloadTemplate = () => {
    // Generate the CSV entirely client-side — no API call needed.
    // This avoids any auth/CORS/ingress quirk that was blocking the download
    // when fetched from the backend.
    const sample =
      "chartink_symbol,nse_symbol,quantity,amount,broker,transaction_type,product\n" +
      "RELIANCE,RELIANCE-EQ,1,,kotak_neo,B,CNC\n" +
      "TCS,TCS,,5000,dhan,B,CNC\n" +
      "INFY,INFY,5,,*,B,CNC\n" +
      "HDFCBANK,HDFCBANK-EQ,,10000,indmoney,B,CNC\n";
    try {
      const blob = new Blob([sample], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "symbol_mappings_template.csv";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      // Defer revoke so the browser definitely picks up the download
      setTimeout(() => {
        a.remove();
        URL.revokeObjectURL(url);
      }, 100);
      toast.success("CSV template downloaded");
    } catch (err) {
      toast.error(err?.message || "Download failed");
    }
  };

  return (
    <Card
      className="bg-surface-2 border-border rounded-sm"
      data-testid="symbol-mappings-card"
    >
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / mapping
          </div>
          <CardTitle className="text-lg font-medium">Symbol Mappings</CardTitle>
          <p className="text-[11px] text-muted-foreground mt-1 max-w-2xl leading-relaxed">
            Translate Chartink symbols → broker NSE symbols and override
            quantity/amount per stock. Symbol mappings take precedence over
            the alert config&apos;s quantity. <span className="text-white">Amount</span>{" "}
            auto-calculates qty using the trigger price from the webhook.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={downloadTemplate}
            data-testid="download-csv-template-button"
            className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3"
          >
            <Download className="w-3.5 h-3.5 mr-1.5" />
            CSV template
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={upload}
            className="hidden"
            data-testid="csv-file-input"
          />
          <Button
            size="sm"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            data-testid="upload-csv-button"
            className="rounded-sm h-8 text-xs bg-brand hover:bg-brand/90 text-white"
          >
            <Upload className="w-3.5 h-3.5 mr-1.5" />
            Upload CSV
          </Button>
          {mappings.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={wipeAll}
              data-testid="wipe-mappings-button"
              className="rounded-sm h-8 text-xs text-muted-foreground hover:text-loss"
            >
              <Trash className="w-3.5 h-3.5 mr-1.5" />
              Wipe all
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Add-single-row form */}
        <form
          onSubmit={add}
          className="grid grid-cols-2 md:grid-cols-8 gap-2 items-end"
          data-testid="add-mapping-form"
        >
          <Field
            label="Chartink"
            value={form.chartink_symbol}
            onChange={(v) => setForm((s) => ({ ...s, chartink_symbol: v }))}
            placeholder="RELIANCE"
            testid="map-chartink-input"
          />
          <Field
            label="NSE symbol"
            value={form.nse_symbol}
            onChange={(v) => setForm((s) => ({ ...s, nse_symbol: v }))}
            placeholder="RELIANCE-EQ"
            testid="map-nse-input"
          />
          <Field
            label="Qty"
            type="number"
            value={form.quantity}
            onChange={(v) => setForm((s) => ({ ...s, quantity: v }))}
            placeholder="1"
            testid="map-qty-input"
          />
          <Field
            label="Amount ₹"
            type="number"
            value={form.amount}
            onChange={(v) => setForm((s) => ({ ...s, amount: v }))}
            placeholder="5000"
            testid="map-amount-input"
          />
          <SelectField
            label="Broker"
            value={form.broker}
            onChange={(v) => setForm((s) => ({ ...s, broker: v }))}
            options={BROKERS}
            testid="map-broker-select"
          />
          <SelectField
            label="Side"
            value={form.transaction_type}
            onChange={(v) => setForm((s) => ({ ...s, transaction_type: v }))}
            options={[
              { value: "B", label: "BUY" },
              { value: "S", label: "SELL" },
            ]}
            testid="map-side-select"
          />
          <SelectField
            label="Product"
            value={form.product}
            onChange={(v) => setForm((s) => ({ ...s, product: v }))}
            options={[
              { value: "CNC", label: "CNC" },
              { value: "MIS", label: "MIS" },
              { value: "NRML", label: "NRML" },
            ]}
            testid="map-product-select"
          />
          <Button
            type="submit"
            disabled={busy}
            data-testid="add-mapping-button"
            className="rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white col-span-2 md:col-span-1"
          >
            <Plus className="w-3.5 h-3.5 mr-1" />
            Add
          </Button>
        </form>

        {/* Existing mappings table */}
        {mappings.length === 0 ? (
          <div className="py-8 text-center text-xs text-muted-foreground border border-dashed border-border rounded-sm">
            No mappings yet. Upload a CSV or add rows manually above.
          </div>
        ) : (
          <Table data-testid="mappings-table">
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <Th>Chartink</Th>
                <Th>NSE</Th>
                <Th className="text-right">Qty</Th>
                <Th className="text-right">Amount</Th>
                <Th>Broker</Th>
                <Th>Side</Th>
                <Th>Product</Th>
                <Th />
              </TableRow>
            </TableHeader>
            <TableBody>
              {mappings.map((m) => (
                <TableRow
                  key={m.id}
                  className="border-border hover:bg-surface-3"
                  data-testid="mapping-row"
                >
                  <TableCell className="font-mono text-xs py-2 px-3">{m.chartink_symbol}</TableCell>
                  <TableCell className="font-mono text-xs py-2 px-3">{m.nse_symbol}</TableCell>
                  <TableCell className="font-mono text-xs py-2 px-3 text-right">{m.quantity ?? "—"}</TableCell>
                  <TableCell className="font-mono text-xs py-2 px-3 text-right">{m.amount ? `₹${m.amount}` : "—"}</TableCell>
                  <TableCell className="text-[10px] py-2 px-3 uppercase tracking-wider text-muted-foreground">
                    {m.broker === "*" ? "any" : m.broker === "kotak_neo" ? "Kotak" : m.broker === "dhan" ? "Dhan" : m.broker === "alice_blue" ? "Alice" : m.broker === "indmoney" ? "INDmoney" : m.broker}
                  </TableCell>
                  <TableCell className="py-2 px-3">
                    <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${m.transaction_type === "B" ? "border-profit/30 text-profit bg-profit/10" : "border-loss/30 text-loss bg-loss/10"}`}>
                      {m.transaction_type === "B" ? "BUY" : "SELL"}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[10px] py-2 px-3 text-muted-foreground">{m.product || "—"}</TableCell>
                  <TableCell className="py-2 px-3 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => remove(m.id)}
                      data-testid="delete-mapping-button"
                      className="h-7 w-7 p-0 rounded-sm text-muted-foreground hover:text-loss"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
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

function Field({ label, value, onChange, type = "text", placeholder, testid }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        {label}
      </Label>
      <Input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-testid={testid}
        className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs"
      />
    </div>
  );
}

function SelectField({ label, value, onChange, options, testid }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        {label}
      </Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          data-testid={testid}
          className="h-9 rounded-sm bg-surface-1 border-border text-xs"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
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
