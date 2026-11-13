"use client";

/**
 * Bank reconciliation (BUILD_PLAN v2.4 change 32; PROMPTS Step 26). Upload a statement CSV (for example
 * the mock bank's, downloaded from a settled payment run). Fixed rules match lines by UTR; a match on
 * amount + date + vendor name is only a suggestion a person accepts. Every action is audited.
 */
import { useState } from "react";
import Link from "next/link";
import { Upload } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
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

const TABS = [
  { id: "suggested", label: "Suggested: please check" },
  { id: "unmatched", label: "Not matched" },
  { id: "matched", label: "Matched" },
] as const;

export default function BankPage() {
  const { data, setData, error, loading } = useApi<View>("/bank-statements");
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("suggested");
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

  const rows = (data?.lines ?? []).filter((l) => l.status === tab);
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
          <div role="tablist" className="flex gap-2">
            {TABS.map((t) => (
              <Button key={t.id} role="tab" aria-selected={tab === t.id} size="sm" variant={tab === t.id ? "default" : "outline"} onClick={() => setTab(t.id)}>
                {t.label} ({data.counts[t.id] ?? 0})
              </Button>
            ))}
          </div>
          {!rows.length ? <EmptyState>Nothing here.</EmptyState> : (
            <div className={table.wrap}><table className={table.table}>
              <thead><tr>{["Date", "Narration", "Reference", "Debit", "Payment", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
              <tbody>{rows.map((l) => (
                <tr key={l.id}>
                  <td className={table.td}>{formatDate(l.date)}</td>
                  <td className={table.td}>{l.narration}</td>
                  <td className={table.td}>{l.reference}</td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(l.debit)}</td>
                  <td className={table.td}>{l.payment ? <>{l.payment.run} · {formatINR(l.payment.net)}{l.method ? <span className="block text-xs text-muted-foreground">by {l.method === "utr" ? "UTR" : "amount, date and name"}</span> : null}</> : "—"}</td>
                  <td className={table.td}>
                    {l.status === "suggested" ? <Button size="sm" onClick={() => void act(`/bank-lines/${l.id}/accept`)}>Accept</Button> : null}
                    {l.status !== "unmatched" ? <Button size="sm" variant="ghost" onClick={() => void act(`/bank-lines/${l.id}/unmatch`)}>Unmatch</Button> : null}
                  </td>
                </tr>))}</tbody>
            </table></div>
          )}
        </div>
      ) : null}
    </>
  );
}
