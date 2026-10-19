"use client";

/**
 * GSTR-2B input-tax-credit matching (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Upload the GSTR-2B JSON
 * from the GST portal; fixed rules match it to Orrfin's invoices and show the credit at risk. Matching
 * only: Orrfin files nothing with GSTN.
 */
import { useState } from "react";
import Link from "next/link";
import { Upload } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { formatDate, formatINR } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Line { supplier: string; gstin: string; invoice_no: string; invoice_date: string; value: string; tax: string; status: string; invoice_id: string | null }
interface Missing { invoice_id: string; invoice_no: string; vendor: string; gstin: string; total: string; tax: string }
interface Period { period: string; imported: boolean; itc_at_risk?: string; counts?: Record<string, number>; lines?: Line[]; missing_in_2b?: Missing[] }
interface View { periods: string[]; current: Period | null; note: string }

const STATUS: Record<string, string> = { matched: "Matched", amount_differs: "Amount differs", not_in_books: "Not in Orrfin" };

export default function GstPage() {
  const [period, setPeriod] = useState<string | null>(null);
  const { data, setData, error, loading } = useApi<View>(`/gstr2b${period ? `?period=${period}` : ""}`);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function upload(file: File) {
    setUploadError(null);
    const body = new FormData();
    body.append("file", file);
    try {
      // Multipart upload: plain fetch, so the browser sets the form boundary itself.
      const response = await fetch("/api/gstr2b", { method: "POST", body, credentials: "same-origin" });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) { setUploadError(typeof json.detail === "string" ? json.detail : "Upload failed."); return; }
      setData(json as View);
      setPeriod((json as View).current?.period ?? null);
    } catch {
      setUploadError("Upload failed.");
    }
  }

  const current = data?.current;
  const tiles: [string, string, string][] = current ? [
    ["ITC at risk", formatINR(current.itc_at_risk), "text-error"],
    ["Matched", String(current.counts?.matched ?? 0), "text-success"],
    ["Amount differs", String(current.counts?.amount_differs ?? 0), "text-warning"],
    ["In 2B, not in Orrfin", String(current.counts?.not_in_books ?? 0), "text-heading"],
  ] : [];
  return (
    <>
      <PageHeader title="GSTR-2B input tax credit"
                  description="Matching only: Orrfin files nothing with GSTN. Credit can be claimed only for invoices your suppliers reported."
                  actions={
                    <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white">
                      <Upload className="size-4" aria-hidden /> Upload GSTR-2B JSON
                      <input type="file" accept=".json,application/json" className="sr-only" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
                    </label>} />
      <ErrorNotice message={error ?? uploadError} />
      {loading ? <Loading /> : !current ? (
        <EmptyState>No GSTR-2B imported yet. For the demo, upload seed/gstr2b/2026-09.json.</EmptyState>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            Period: {data?.periods.map((p) => (
              <button key={p} type="button" onClick={() => setPeriod(p)}
                      className={`rounded-md px-2 py-1 ${p === current.period ? "bg-navy text-white" : "bg-ice text-heading"}`}>{p}</button>))}
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            {tiles.map(([label, value, tone]) => (
              <div key={label} className="rounded-xl border border-border bg-white px-4 py-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className={`text-xl font-semibold tabular-nums ${tone}`}>{value}</p>
              </div>
            ))}
          </div>
          <Panel title="In Orrfin, missing from GSTR-2B (credit at risk until the supplier reports it)">
            {current.missing_in_2b?.length ? (
              <ul className="text-sm">{current.missing_in_2b.map((m) => (
                <li key={m.invoice_id}>
                  <Link href={`/invoices/${m.invoice_id}`} className="text-primary hover:underline">{m.invoice_no}</Link> · {m.vendor} · {m.gstin} · GST {formatINR(m.tax)}
                </li>))}</ul>
            ) : <p className="text-sm text-success">Every invoice of the period is in GSTR-2B.</p>}
            <p className="mt-2 text-xs text-muted-foreground">Paying one of these invoices needs the approver&apos;s reason (payment-risk hold).</p>
          </Panel>
          <div className={table.wrap}><table className={table.table}>
            <thead><tr>{["Supplier", "GSTIN", "Invoice", "Date", "Value", "GST", "Result"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
            <tbody>{current.lines?.map((l) => (
              <tr key={`${l.gstin}-${l.invoice_no}`}>
                <td className={table.td}>{l.supplier}</td>
                <td className={table.td}>{l.gstin}</td>
                <td className={table.td}>{l.invoice_id ? <Link href={`/invoices/${l.invoice_id}`} className="text-primary hover:underline">{l.invoice_no}</Link> : l.invoice_no}</td>
                <td className={table.td}>{formatDate(l.invoice_date)}</td>
                <td className={`${table.td} ${table.num}`}>{formatINR(l.value)}</td>
                <td className={`${table.td} ${table.num}`}>{formatINR(l.tax)}</td>
                <td className={table.td}>{STATUS[l.status] ?? l.status}</td>
              </tr>))}</tbody>
          </table></div>
        </div>
      )}
    </>
  );
}
