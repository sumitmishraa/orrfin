"use client";

/**
 * Bank reconciliation (BUILD_PLAN v2.4 change 32; PROMPTS Step 26). Upload a statement CSV (for example
 * the mock bank's, downloaded from a settled payment run). Fixed rules match lines by UTR; a match on
 * amount + date + vendor name is only a suggestion a person accepts. Every action is audited.
 */
import { useState } from "react";
import Link from "next/link";
import { CircleCheck, CircleHelp, CircleMinus, Upload } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { StatusPill } from "@/components/ui/display";
import { Button } from "@/components/ui/button";
import { APP_HEADERS, post } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface View {
  lines: { id: string; statement: string; date: string; narration: string; reference: string; debit: string; credit: string;
           status: "matched" | "suggested" | "unmatched"; method: string | null;
           payment: { run: string; run_id: string; net: string; utr: string | null } | null }[];
  unreconciled_payments: { run: string; run_id: string; net: string; utr: string }[];
  counts: Record<string, number>;
}

type Line = View["lines"][number];

function LineStatus({ line }: { line: Line }) {
  if (line.status === "matched") return <StatusPill tone="success" icon={CircleCheck}>Matched{line.method === "utr" ? " by UTR" : ""}</StatusPill>;
  if (line.status === "suggested") return <StatusPill tone="warning" icon={CircleHelp}>Suggested: please check</StatusPill>;
  return <StatusPill tone="muted" icon={CircleMinus}>Not matched</StatusPill>;
}

export default function BankPage() {
  const { data, setData, error, loading } = useApi<View>("/bank-statements");
  const [actionError, setActionError] = useState<string | null>(null);

  async function upload(file: File) {
    setActionError(null);
    const body = new FormData();
    body.append("file", file);
    try {
      // Multipart upload: plain fetch, so the browser sets the form boundary itself.
      const response = await fetch("/api/bank-statements", { method: "POST", body, credentials: "same-origin", headers: APP_HEADERS });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Upload failed.");
      setData(json as View);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Upload failed.");
    }
  }

  async function act(path: string) {
    setActionError(null);
    try {
      setData(await post<View>(path));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  return (
    <>
      <PageHeader title="Bank reconciliation"
                  description="Rules match statement lines to payments by UTR. Anything less certain is a suggestion for you to accept."
                  actions={
                    <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white">
                      <Upload className="size-4" aria-hidden /> Upload statement CSV
                      <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
                    </label>} />
      <ErrorNotice message={error ?? actionError} />
      {loading ? <Loading /> : data ? (
        <div className="flex flex-col gap-6">
          {data.unreconciled_payments.length ? (
            <Panel title={`Payments not yet on a statement · ${data.unreconciled_payments.length}`}>
              <ul className="text-sm">{data.unreconciled_payments.map((p) => (
                <li key={p.utr}><Link href={`/payments/${p.run_id}`} className="text-primary hover:underline">{p.run}</Link> · UTR {p.utr} · {formatINR(p.net)}</li>))}</ul>
              <p className="mt-2 text-xs text-muted-foreground">Download the bank statement from a settled payment run and upload it here.</p>
            </Panel>
          ) : null}
          <DataTable rows={data.lines} rowKey={(l) => l.id} noun={["statement line", "statement lines"]}
                     initialFilter={data.counts.suggested ? "suggested" : undefined}
                     empty="No statement lines yet. Upload a statement CSV."
                     filters={[
                       { key: "suggested", label: "Suggested", test: (l) => l.status === "suggested" },
                       { key: "unmatched", label: "Not matched", test: (l) => l.status === "unmatched" },
                       { key: "matched", label: "Matched", test: (l) => l.status === "matched" },
                     ]}
                     columns={[
                       { key: "date", header: "Date", sortValue: (l) => l.date, cell: (l) => formatDate(l.date) },
                       { key: "narration", header: "Narration", searchValue: (l) => `${l.narration} ${l.reference}`,
                         cell: (l) => <span className="block leading-tight"><span>{l.narration}</span><span className="mt-0.5 block font-mono text-xs text-muted-foreground">{l.reference}</span></span> },
                       { key: "debit", header: "Debit", align: "right", sortValue: (l) => Number(l.debit), cell: (l) => <span className="font-medium">{formatINR(l.debit)}</span> },
                       { key: "status", header: "Result", sortValue: (l) => l.status, cell: (l) => <LineStatus line={l} /> },
                       { key: "payment", header: "Payment", searchValue: (l) => l.payment?.run,
                         cell: (l) => l.payment ? <span className="block leading-tight"><span>{l.payment.run}</span><span className="mt-0.5 block text-xs text-muted-foreground">{formatINR(l.payment.net)}{l.method && l.method !== "utr" ? " · by amount, date and name" : ""}</span></span> : <span className="text-muted-foreground">—</span> },
                       { key: "actions", header: "", align: "right", cell: (l) => (
                         <span className="inline-flex gap-1">
                           {l.status === "suggested" ? <Button size="sm" onClick={() => void act(`/bank-lines/${l.id}/accept`)}>Accept</Button> : null}
                           {l.status !== "unmatched" ? <Button size="sm" variant="ghost" onClick={() => void act(`/bank-lines/${l.id}/unmatch`)}>Unmatch</Button> : null}
                         </span>
                       ) },
                     ]} />
        </div>
      ) : null}
    </>
  );
}
