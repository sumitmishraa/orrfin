"use client";

/**
 * Invoices (PROMPTS Step 7): upload a supplier invoice PDF and see every invoice with its status,
 * match outcome and ₹ at risk. Finance and admins upload; buyers and approvers can look.
 */
import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Upload } from "lucide-react";

import { InvoiceStatus } from "@/components/invoice-status";
import { EmptyState, ErrorNotice, Loading, PageHeader, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { API_URL } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";
import type { InvoiceDetail, InvoiceSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function UploadButton() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    // Multipart upload: no JSON content type, so this bypasses the JSON helper on purpose.
    const response = await fetch(`${API_URL}/invoices`, { method: "POST", body: form, credentials: "same-origin" });
    const body = await response.json().catch(() => ({}));
    setBusy(false);
    if (!response.ok) {
      setError(typeof body.detail === "string" ? body.detail : "Upload failed.");
      return;
    }
    router.push(`/invoices/${(body as InvoiceDetail).id}`);
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <input ref={input} type="file" accept="application/pdf" className="sr-only" aria-label="Invoice PDF"
             onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      <Button size="lg" disabled={busy} onClick={() => input.current?.click()}>
        <Upload aria-hidden /> {busy ? "Uploading…" : "Upload invoice PDF"}
      </Button>
      <p className="text-xs text-muted-foreground">PDF only, up to 10 MB.</p>
      {error ? <div className="max-w-sm"><ErrorNotice message={error} /></div> : null}
    </div>
  );
}

export default function InvoicesPage() {
  const me = useMe();
  const { data, error, loading } = useApi<InvoiceSummary[]>("/invoices");
  const canUpload = me.role === "finance" || me.role === "admin";

  return (
    <>
      <PageHeader
        title="Invoices"
        description="Each invoice is read, checked line by line against its PO and goods receipt, then decided by a named person."
        actions={canUpload ? <UploadButton /> : undefined}
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : !data?.length ? (
        <EmptyState>No invoices yet. {canUpload ? "Upload one of the PDFs in evals/extraction/ to try it." : ""}</EmptyState>
      ) : (
        <div className={table.wrap}>
          <table className={table.table}>
            <thead>
              <tr>
                <th className={table.th}>Invoice</th>
                <th className={table.th}>Vendor</th>
                <th className={table.th}>PO</th>
                <th className={table.th}>Status</th>
                <th className={`${table.th} ${table.num}`}>Total</th>
                <th className={`${table.th} ${table.num}`}>At risk</th>
              </tr>
            </thead>
            <tbody>
              {data.map((inv) => (
                <tr key={inv.id} className="hover:bg-ice-light">
                  <td className={table.td}>
                    <Link href={`/invoices/${inv.id}`} className="font-medium text-primary hover:underline">
                      {inv.invoice_no ?? inv.filename}
                    </Link>
                    <p className="text-xs text-muted-foreground">{formatDate(inv.invoice_date ?? inv.created_at)}</p>
                  </td>
                  <td className={table.td}>{inv.vendor_name ?? "—"}</td>
                  <td className={`${table.td} font-mono text-xs`}>{inv.po_reference ?? "—"}</td>
                  <td className={table.td}><InvoiceStatus status={inv.outcome === "stale" ? "stale" : inv.status} /></td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(inv.total)}</td>
                  <td className={`${table.td} ${table.num} ${inv.amount_at_risk && inv.amount_at_risk !== "0.00" ? "font-semibold text-error" : ""}`}>
                    {inv.amount_at_risk && inv.amount_at_risk !== "0.00" ? formatINR(inv.amount_at_risk) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
