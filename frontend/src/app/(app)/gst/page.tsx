"use client";

/**
 * GSTR-2B input-tax-credit matching (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Upload the GSTR-2B JSON
 * from the GST portal; fixed rules match it to Orrfin's invoices and show the credit at risk. Matching
 * only: Orrfin files nothing with GSTN.
 */
import { useState } from "react";
import Link from "next/link";
import { CircleCheck, CircleHelp, TriangleAlert, Upload } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { StatusPill } from "@/components/ui/display";
import { APP_HEADERS } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Line { supplier: string; gstin: string; invoice_no: string; invoice_date: string; value: string; tax: string; status: string; invoice_id: string | null }
interface Missing { invoice_id: string; invoice_no: string; vendor: string; gstin: string; total: string; tax: string }
interface Period { period: string; imported: boolean; itc_at_risk?: string; counts?: Record<string, number>; lines?: Line[]; missing_in_2b?: Missing[] }
interface View { periods: string[]; current: Period | null; note: string }

const STATUS: Record<string, string> = { matched: "Matched", amount_differs: "Amount differs", not_in_books: "Not in Orrfin" };

function Result({ status }: { status: string }) {
  if (status === "matched") return <StatusPill tone="success" icon={CircleCheck}>Matched</StatusPill>;
  if (status === "amount_differs") return <StatusPill tone="warning" icon={TriangleAlert}>Amount differs</StatusPill>;
  return <StatusPill tone="info" icon={CircleHelp}>{STATUS[status] ?? status}</StatusPill>;
}

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
      const response = await fetch("/api/gstr2b", { method: "POST", body, credentials: "same-origin", headers: APP_HEADERS });
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
                      aria-pressed={p === current.period}
                      className={`h-7 rounded-full border px-3 text-xs font-medium ${p === current.period ? "border-primary bg-primary text-white" : "border-border bg-white text-heading hover:bg-ice"}`}>{p}</button>))}
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            {tiles.map(([label, value, tone]) => (
              <div key={label} className="rounded-xl border border-border bg-white px-4 py-3 shadow-raised">
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
          <DataTable rows={current.lines ?? []} rowKey={(l) => `${l.gstin}-${l.invoice_no}`} noun={["GSTR-2B line", "GSTR-2B lines"]}
                     rowHref={(l) => (l.invoice_id ? `/invoices/${l.invoice_id}` : "/gst")}
                     filters={[{ key: "matched", label: "Matched", test: (l) => l.status === "matched" },
                               { key: "differs", label: "Amount differs", test: (l) => l.status === "amount_differs" },
                               { key: "missing", label: "Not in Orrfin", test: (l) => l.status === "not_in_books" }]}
                     columns={[
                       { key: "supplier", header: "Supplier", sortValue: (l) => l.supplier, searchValue: (l) => `${l.supplier} ${l.gstin}`,
                         cell: (l) => <span className="block leading-tight"><span className="font-medium">{l.supplier}</span><span className="mt-0.5 block font-mono text-xs text-muted-foreground">{l.gstin}</span></span> },
                       { key: "invoice", header: "Invoice", searchValue: (l) => l.invoice_no, cell: (l) => <span className={l.invoice_id ? "font-medium text-primary" : undefined}>{l.invoice_no}</span> },
                       { key: "date", header: "Date", sortValue: (l) => l.invoice_date, cell: (l) => formatDate(l.invoice_date) },
                       { key: "value", header: "Value", align: "right", sortValue: (l) => Number(l.value), cell: (l) => formatINR(l.value) },
                       { key: "tax", header: "GST", align: "right", sortValue: (l) => Number(l.tax), cell: (l) => formatINR(l.tax) },
                       { key: "result", header: "Result", sortValue: (l) => l.status, cell: (l) => <Result status={l.status} /> },
                     ]} />
        </div>
      )}
    </>
  );
}
