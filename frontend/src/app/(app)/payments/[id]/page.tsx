"use client";

/**
 * One payment run (PROMPTS Step 25): add due invoices (TDS and risk checks computed by fixed rules),
 * submit, approve with a reason when there are holds, download the bank file, send it to the mock bank,
 * and see each payment's UTR. Buttons follow the server's `allowed`; the server enforces every rule.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { Download, Landmark, Send, ShieldAlert, ShieldX } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/field";
import { api, post } from "@/lib/api";
import { formatDateTime, formatINR, RUN_STATUS } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Risk { code: string; level: "block" | "hold"; message: string }
interface Run {
  id: string; label: string; status: string; prepared_by: string; approved_by: string | null; approved_at: string | null;
  hold_reason: string | null; total_gross: string; total_tds: string; total_net: string; settled_at: string | null;
  holds: string[]; blocks: string[];
  lines: { id: string; invoice_id: string; invoice_no: string; vendor: string; gross: string; tds_section: string | null;
           tds_rate: string; tds_amount: string; net: string; risk: Risk[]; status: string; utr: string | null; failure_reason: string | null }[];
  allowed: { edit: boolean; submit: boolean; approve: boolean; approve_blocked_reason: string | null; send: boolean; cancel: boolean };
}

export default function PaymentRunPage() {
  const { id } = useParams<{ id: string }>();
  const { data: run, setData, error, loading, reload } = useApi<Run>(`/payment-runs/${id}`);
  const due = useApi<{ invoice_id: string; invoice_no: string; vendor: string; left_to_pay: string }[]>("/payments/eligible");
  const [pick, setPick] = useState("");
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  if (loading) return <Loading />;
  if (error || !run) return <ErrorNotice message={error ?? "Run not found."} />;

  async function act(fn: () => Promise<Run>) {
    setActionError(null);
    try {
      setData(await fn());
      void due.reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  async function download(kind: "bank-file" | "bank-statement" | "advice") {
    const response = await fetch(`/api/payment-runs/${id}/${kind}`, { credentials: "same-origin" });
    if (!response.ok) { setActionError((await response.json().catch(() => ({}))).detail ?? "Download failed."); return; }
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${run!.label}-${kind}.${kind === "advice" ? "pdf" : "csv"}`;
    a.click();
    URL.revokeObjectURL(url);
    void reload();
  }

  return (
    <>
      <PageHeader title={`${run.label} · ${RUN_STATUS[run.status] ?? run.status}`}
                  description={`Prepared by ${run.prepared_by}${run.approved_by ? ` · approved by ${run.approved_by} on ${formatDateTime(run.approved_at!)}` : ""}. Simulated: no real money moves.`} />
      <div className="flex flex-col gap-6">
        <div className="grid gap-3 sm:grid-cols-3">
          {[["Gross", run.total_gross], ["TDS deducted", run.total_tds], ["Net to pay", run.total_net]].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-border bg-white px-4 py-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="text-xl font-semibold tabular-nums text-heading">{formatINR(value)}</p>
            </div>
          ))}
        </div>
        <ErrorNotice message={actionError} />

        {run.allowed.edit ? (
          <Panel title="Add an approved invoice">
            <div className="flex flex-wrap gap-2">
              <Select aria-label="Invoice to pay" className="w-96" value={pick} onChange={(e) => setPick(e.target.value)}>
                <option value="">Choose an invoice</option>
                {(due.data ?? []).map((d) => <option key={d.invoice_id} value={d.invoice_id}>{d.invoice_no} · {d.vendor} · {formatINR(d.left_to_pay)}</option>)}
              </Select>
              <Button disabled={!pick} onClick={() => void act(() => post<Run>(`/payment-runs/${id}/invoices`, { invoice_id: pick })).then(() => setPick(""))}>Add</Button>
            </div>
          </Panel>
        ) : null}

        <div className={table.wrap}><table className={table.table}>
          <thead><tr>{["Invoice", "Vendor", "Gross", "TDS", "Net", "Risk checks", "Bank result", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
          <tbody>{run.lines.map((ln) => (
            <tr key={ln.id}>
              <td className={table.td}>{ln.invoice_no}</td>
              <td className={table.td}>{ln.vendor}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(ln.gross)}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(ln.tds_amount)}{ln.tds_section ? <span className="block text-xs text-muted-foreground">{ln.tds_section} @ {Number(ln.tds_rate)}%</span> : null}</td>
              <td className={`${table.td} ${table.num} font-medium`}>{formatINR(ln.net)}</td>
              <td className={table.td}>
                {ln.risk.length ? ln.risk.map((r) => (
                  <p key={r.code} className={`flex items-start gap-1 text-xs ${r.level === "block" ? "text-error" : "text-warning"}`}>
                    {r.level === "block" ? <ShieldX className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
                    {r.level === "block" ? "Block" : "Hold"}: {r.message}
                  </p>)) : <span className="text-xs text-success">All checks passed</span>}
              </td>
              <td className={table.td}>{ln.utr ? <span className="text-success">Paid · UTR {ln.utr}</span> : ln.status === "failed" ? <span className="text-error">Failed: {ln.failure_reason}</span> : "—"}</td>
              <td className={table.td}>{run.allowed.edit ? <Button size="sm" variant="ghost" onClick={() => void act(() => api<Run>(`/payment-runs/${id}/lines/${ln.id}`, { method: "DELETE" }))}>Remove</Button> : null}</td>
            </tr>))}</tbody>
        </table></div>

        <div className="flex flex-wrap gap-2">
          {run.allowed.submit ? <Button onClick={() => void act(() => post<Run>(`/payment-runs/${id}/submit`))}>Submit for approval</Button> : null}
          {run.status === "submitted" && !run.allowed.approve && run.allowed.approve_blocked_reason ? (
            <p className="text-sm text-muted-foreground">You cannot approve: {run.allowed.approve_blocked_reason}</p>) : null}
          {["approved", "sent", "settled", "partly_failed"].includes(run.status) ? (
            <Button variant="outline" onClick={() => void download("bank-file")}><Download aria-hidden /> Bank file (CSV)</Button>) : null}
          {run.allowed.send ? <Button onClick={() => void act(() => post<Run>(`/payment-runs/${id}/send`)).then(() => setTimeout(() => void reload(), 2500))}><Send aria-hidden /> Send to bank (simulated)</Button> : null}
          {["settled", "partly_failed"].includes(run.status) ? (
            <Button variant="outline" onClick={() => void download("bank-statement")}><Landmark aria-hidden /> Bank statement (CSV)</Button>) : null}
            {run.status === "settled" || run.status === "partly_failed" ? (
              <Button variant="outline" onClick={() => void download("advice")}>Payment advice (PDF)</Button>) : null}
          {run.status === "sent" ? <Button variant="outline" onClick={() => void reload()}>Refresh</Button> : null}
          {run.allowed.cancel ? <Button variant="ghost" onClick={() => void act(() => post<Run>(`/payment-runs/${id}/cancel`))}>Cancel run</Button> : null}
        </div>

        {run.allowed.approve ? (
          <Panel title="Approve this payment run">
            <div className="flex flex-col gap-2">
              {run.holds.length ? <p className="text-sm text-warning">Holds to accept: {run.holds.join(", ")}. Give a reason (for example, how you confirmed a bank change).</p> : null}
              <Field label="Reason" htmlFor="reason"><Textarea id="reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
              <Button className="self-start" onClick={() => void act(() => post<Run>(`/payment-runs/${id}/approve`, { reason }))}>Approve {formatINR(run.total_net)}</Button>
            </div>
          </Panel>
        ) : null}
        {run.hold_reason ? <p className="text-sm text-muted-foreground">Approver&apos;s reason: “{run.hold_reason}”</p> : null}
      </div>
    </>
  );
}
