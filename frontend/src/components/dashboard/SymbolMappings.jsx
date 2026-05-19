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
import {
  Plus, Trash2, Upload, Download, Trash,
  Pencil, Save, X, Search, ChevronDown, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const BROKERS = [
  { value: "*", label: "Any" },
  { value: "kotak_neo", label: "Kotak" },
  { value: "dhan", label: "Dhan" },
  { value: "alice_blue", label: "Alice" },
  { value: "indmoney", label: "INDmoney" },
];

const CATEGORIES = [
  { value: "none", label: "—" },
  { value: "large_cap", label: "Large Cap" },
  { value: "mid_cap", label: "Mid Cap" },
  { value: "small_cap", label: "Small Cap" },
  { value: "other", label: "Other" },
];

const blank = {
  chartink_symbol: "",
  nse_symbol: "",
  quantity: "",
  amount: "",
  broker: "*",
  transaction_type: "B",
  product: "CNC",
  category: "none",
};

export default function SymbolMappings() {
  const [mappings, setMappings] = useState([]);
  const [catAmounts, setCatAmounts] = useState({});
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [catOpen, setCatOpen] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [mRes, cRes] = await Promise.all([
        api.get("/symbol-mappings"),
        api.get("/symbol-mappings/category-amounts"),
      ]);
      setMappings(mRes.data.mappings || []);
      const catMap = {};
      (cRes.data.amounts || []).forEach((a) => { catMap[a.category] = a.amount; });
      setCatAmounts(catMap);
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
        category: form.category === "none" ? null : form.category,
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
      if (errors?.length) msg += ` \u2014 ${errors.length} skipped`;
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
    const sample =
      "chartink_symbol,nse_symbol,quantity,amount,broker,transaction_type,product,category\n" +
      "RELIANCE,RELIANCE-EQ,1,,kotak_neo,B,CNC,large_cap\n" +
      "TCS,TCS,,5000,dhan,B,CNC,large_cap\n" +
      "INFY,INFY,5,,*,B,CNC,\n" +
      "HDFCBANK,HDFCBANK-EQ,,10000,indmoney,B,CNC,mid_cap\n";
    try {
      const blob = new Blob([sample], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "symbol_mappings_template.csv";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 100);
      toast.success("CSV template downloaded");
    } catch (err) {
      toast.error(err?.message || "Download failed");
    }
  };

  // ---- Inline edit ----
  const startEdit = (m) => {
    setEditingId(m.id);
    setEditForm({
      chartink_symbol: m.chartink_symbol,
      nse_symbol: m.nse_symbol,
      quantity: m.quantity != null ? String(m.quantity) : "",
      amount: m.amount != null ? String(m.amount) : "",
      broker: m.broker,
      transaction_type: m.transaction_type,
      product: m.product || "CNC",
      category: m.category || "none",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({});
  };

  const saveEdit = async (id) => {
    const payload = { ...editForm };
    payload.quantity = payload.quantity ? Number(payload.quantity) : null;
    payload.amount = payload.amount ? Number(payload.amount) : null;
    payload.category = editForm.category === "none" ? null : editForm.category;
    try {
      await api.put(`/symbol-mappings/${id}`, payload);
      toast.success("Updated");
      setEditingId(null);
      setEditForm({});
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Update failed");
    }
  };

  const setCatAmount = async (category, value) => {
    const amt = parseFloat(value);
    if (isNaN(amt) || amt <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    try {
      await api.post("/symbol-mappings/category-amounts", { category, amount: amt });
      toast.success(`${category.replace("_", " ")} amount set to \u20B9${amt}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save");
    }
  };

  // Filter by search
  const q = search.toLowerCase().trim();
  const filtered = q
    ? mappings.filter(
        (m) =>
          m.chartink_symbol.toLowerCase().includes(q) ||
          m.nse_symbol.toLowerCase().includes(q) ||
          (m.broker || "").toLowerCase().includes(q)
      )
    : mappings;

  return (
    <Card className="bg-surface-2 border-border rounded-sm" data-testid="symbol-mappings-card">
      <CardHeader className="pb-3 flex flex-row items-start justify-between space-y-0">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1 font-semibold">
            / mapping
          </div>
          <CardTitle className="text-lg font-medium">Symbol Mappings</CardTitle>
          <p className="text-[11px] text-muted-foreground mt-1 max-w-2xl leading-relaxed">
            Translate Chartink symbols \u2192 broker NSE symbols and override
            quantity/amount per stock. Symbol mappings take precedence over
            the alert config&apos;s quantity. <span className="text-white">Amount</span>{" "}
            auto-calculates qty using the trigger price from the webhook.
            Category amounts apply when a mapping has a category but no explicit qty or amount.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={downloadTemplate}
            data-testid="download-csv-template-button"
            className="rounded-sm h-8 text-xs border-border bg-surface-1 hover:bg-surface-3">
            <Download className="w-3.5 h-3.5 mr-1.5" />
            CSV template
          </Button>
          <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={upload}
            className="hidden" data-testid="csv-file-input" />
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={busy}
            data-testid="upload-csv-button"
            className="rounded-sm h-8 text-xs bg-brand hover:bg-brand/90 text-white">
            <Upload className="w-3.5 h-3.5 mr-1.5" />
            Upload CSV
          </Button>
          {mappings.length > 0 && (
            <Button size="sm" variant="ghost" onClick={wipeAll}
              data-testid="wipe-mappings-button"
              className="rounded-sm h-8 text-xs text-muted-foreground hover:text-loss">
              <Trash className="w-3.5 h-3.5 mr-1.5" />
              Wipe all
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* --- Category Amounts --- */}
        <div className="border border-border rounded-sm">
          <button
            onClick={() => setCatOpen(!catOpen)}
            className="w-full flex items-center gap-2 px-3 py-2 text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold hover:bg-surface-3 transition-colors"
          >
            {catOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Amount by Market Cap
          </button>
          {catOpen && (
            <div className="px-3 pb-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
              {["large_cap", "mid_cap", "small_cap", "other"].map((cat) => (
                <div key={cat} className="space-y-1">
                  <Label className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {cat.replace("_", " ")}
                  </Label>
                  <div className="flex gap-1">
                    <Input
                      type="number"
                      placeholder="Amount"
                      defaultValue={catAmounts[cat] || ""}
                      data-testid={`cat-amount-${cat}`}
                      className="h-8 rounded-sm bg-surface-1 border-border font-mono text-xs flex-1"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        const inp = e.currentTarget.closest("div").querySelector("input");
                        setCatAmount(cat, inp.value);
                      }}
                      className="h-8 rounded-sm text-[10px] border-border"
                    >
                      Set
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* --- Search + Add form row --- */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search symbols..."
              data-testid="search-mappings-input"
              className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs pl-8"
            />
          </div>
        </div>

        {/* Add-single-row form */}
        <form onSubmit={add} className="grid grid-cols-2 md:grid-cols-9 gap-2 items-end"
          data-testid="add-mapping-form">
          <Field label="Chartink" value={form.chartink_symbol}
            onChange={(v) => setForm((s) => ({ ...s, chartink_symbol: v }))}
            placeholder="RELIANCE" testid="map-chartink-input" />
          <Field label="NSE symbol" value={form.nse_symbol}
            onChange={(v) => setForm((s) => ({ ...s, nse_symbol: v }))}
            placeholder="RELIANCE-EQ" testid="map-nse-input" />
          <Field label="Qty" type="number" value={form.quantity}
            onChange={(v) => setForm((s) => ({ ...s, quantity: v }))}
            placeholder="1" testid="map-qty-input" />
          <Field label="Amount \u20B9" type="number" value={form.amount}
            onChange={(v) => setForm((s) => ({ ...s, amount: v }))}
            placeholder="5000" testid="map-amount-input" />
          <SelectField label="Broker" value={form.broker}
            onChange={(v) => setForm((s) => ({ ...s, broker: v }))}
            options={BROKERS} testid="map-broker-select" />
          <SelectField label="Side" value={form.transaction_type}
            onChange={(v) => setForm((s) => ({ ...s, transaction_type: v }))}
            options={[{ value: "B", label: "BUY" }, { value: "S", label: "SELL" }]}
            testid="map-side-select" />
          <SelectField label="Product" value={form.product}
            onChange={(v) => setForm((s) => ({ ...s, product: v }))}
            options={[{ value: "CNC", label: "CNC" }, { value: "MIS", label: "MIS" }, { value: "NRML", label: "NRML" }]}
            testid="map-product-select" />
          <SelectField label="Category" value={form.category}
            onChange={(v) => setForm((s) => ({ ...s, category: v }))}
            options={CATEGORIES} testid="map-category-select" />
          <Button type="submit" disabled={busy}
            data-testid="add-mapping-button"
            className="rounded-sm h-9 text-xs bg-brand hover:bg-brand/90 text-white col-span-2 md:col-span-1">
            <Plus className="w-3.5 h-3.5 mr-1" />
            Add
          </Button>
        </form>

        {/* Mappings table */}
        {filtered.length === 0 ? (
          <div className="py-8 text-center text-xs text-muted-foreground border border-dashed border-border rounded-sm">
            {q ? "No mappings match your search." : "No mappings yet. Upload a CSV or add rows manually above."}
          </div>
        ) : (
          <div className="border border-border rounded-sm overflow-x-auto">
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
                  <Th>Category</Th>
                  <Th className="text-right w-20">Actions</Th>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((m) => (
                  <TableRow key={m.id} className="border-border hover:bg-surface-3"
                    data-testid="mapping-row">
                    {editingId === m.id ? (
                      <>
                        <EditCell value={editForm.chartink_symbol}
                          onChange={(v) => setEditForm((s) => ({ ...s, chartink_symbol: v }))} />
                        <EditCell value={editForm.nse_symbol}
                          onChange={(v) => setEditForm((s) => ({ ...s, nse_symbol: v }))} />
                        <EditCell value={editForm.quantity} type="number"
                          onChange={(v) => setEditForm((s) => ({ ...s, quantity: v }))}
                          className="text-right" />
                        <EditCell value={editForm.amount} type="number"
                          onChange={(v) => setEditForm((s) => ({ ...s, amount: v }))}
                          className="text-right" />
                        <EditSelect value={editForm.broker} options={BROKERS}
                          onChange={(v) => setEditForm((s) => ({ ...s, broker: v }))} />
                        <EditSelect value={editForm.transaction_type}
                          options={[{ value: "B", label: "BUY" }, { value: "S", label: "SELL" }]}
                          onChange={(v) => setEditForm((s) => ({ ...s, transaction_type: v }))} />
                        <EditSelect value={editForm.product}
                          options={[{ value: "CNC", label: "CNC" }, { value: "MIS", label: "MIS" }, { value: "NRML", label: "NRML" }]}
                          onChange={(v) => setEditForm((s) => ({ ...s, product: v }))} />
                        <EditSelect value={editForm.category} options={CATEGORIES}
                          onChange={(v) => setEditForm((s) => ({ ...s, category: v }))} />
                        <TableCell className="py-1 px-2 text-right">
                          <div className="flex gap-1 justify-end">
                            <Button size="sm" variant="ghost" onClick={() => saveEdit(m.id)}
                              className="h-7 w-7 p-0 rounded-sm text-profit hover:text-profit">
                              <Save className="w-3.5 h-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" onClick={cancelEdit}
                              className="h-7 w-7 p-0 rounded-sm text-muted-foreground hover:text-loss">
                              <X className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </>
                    ) : (
                      <>
                        <Cell>{m.chartink_symbol}</Cell>
                        <Cell>{m.nse_symbol}</Cell>
                        <Cell className="text-right">{m.quantity ?? "\u2014"}</Cell>
                        <Cell className="text-right">{m.amount ? `\u20B9${m.amount}` : "\u2014"}</Cell>
                        <Cell className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          {m.broker === "*" ? "any" : m.broker === "kotak_neo" ? "Kotak" : m.broker === "dhan" ? "Dhan" : m.broker === "alice_blue" ? "Alice" : m.broker === "indmoney" ? "INDmoney" : m.broker}
                        </Cell>
                        <Cell>
                          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${m.transaction_type === "B" ? "border-profit/30 text-profit bg-profit/10" : "border-loss/30 text-loss bg-loss/10"}`}>
                            {m.transaction_type === "B" ? "BUY" : "SELL"}
                          </span>
                        </Cell>
                        <Cell className="font-mono text-[10px] text-muted-foreground">{m.product || "\u2014"}</Cell>
                        <Cell>
                          {m.category ? (
                            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-warn/30 text-warn bg-warn/10">
                              {m.category.replace("_", " ")}
                            </span>
                          ) : (
                            <span className="text-muted-foreground/50 text-[10px]">\u2014</span>
                          )}
                        </Cell>
                        <TableCell className="py-1 px-2 text-right">
                          <div className="flex gap-1 justify-end">
                            <Button size="sm" variant="ghost" onClick={() => startEdit(m)}
                              data-testid="edit-mapping-button"
                              className="h-7 w-7 p-0 rounded-sm text-muted-foreground hover:text-brand">
                              <Pencil className="w-3.5 h-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => remove(m.id)}
                              data-testid="delete-mapping-button"
                              className="h-7 w-7 p-0 rounded-sm text-muted-foreground hover:text-loss">
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---- Helper components ----

function Field({ label, value, onChange, type = "text", placeholder, testid }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
        {label}
      </Label>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} data-testid={testid}
        className="h-9 rounded-sm bg-surface-1 border-border font-mono text-xs" />
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
        <SelectTrigger data-testid={testid} className="h-9 rounded-sm bg-surface-1 border-border text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
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

function Cell({ children, className = "" }) {
  return <TableCell className={`font-mono text-xs py-2 px-3 ${className}`}>{children}</TableCell>;
}

function EditCell({ value, onChange, type = "text", className = "" }) {
  return (
    <TableCell className={`py-1 px-1 ${className}`}>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-sm bg-surface-1 border-border font-mono text-xs" />
    </TableCell>
  );
}

function EditSelect({ value, onChange, options }) {
  return (
    <TableCell className="py-1 px-1">
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="h-8 rounded-sm bg-surface-1 border-border text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TableCell>
  );
}
