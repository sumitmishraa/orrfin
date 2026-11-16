"use client";

/**
 * Invoices (PROMPTS Step 7): upload a supplier invoice PDF and see every invoice with its status,
 * match outcome and ₹ at risk. Finance and admins upload; buyers and approvers can look.
 */
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Upload } from "lucide-react";

import { InvoiceTable } from "@/components/invoice-table";
import { ErrorNotice, PageHeader } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { API_URL, APP_HEADERS } from "@/lib/api";
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
    const response = await fetch(`${API_URL}/invoices`, { method: "POST", body: form, credentials: "same-origin", headers: APP_HEADERS });
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
      <input ref={input} type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only" aria-label="Invoice PDF"
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
      <InvoiceTable rows={data} loading={loading}
                    empty={canUpload ? "No invoices yet. Upload one of the PDFs in evals/extraction/ to try it." : "No invoices yet."} />
    </>
  );
}
