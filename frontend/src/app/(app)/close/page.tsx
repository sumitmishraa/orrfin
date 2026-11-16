"use client";

/**
 * Month-end close cockpit (BUILD_PLAN v2.4 change 32; PROMPTS Step 26): the live checklist, the
 * received-not-invoiced report (for the accountant's accrual; Orrfin posts no journal), AI "what changed"
 * notes, and the named sign-off. A closed month refuses approvals dated in it until an admin reopens it.
 */
import { useState } from "react";
import { CircleCheck, Download, Lock, TriangleAlert } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDateTime, formatINR, formatQty } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Close {
  period: string; status: "open" | "closed"; closed_by: string | null; closed_at: string | null; reopen_reason: string | null;
  checklist: { key: string; label: string; open: number; ok: boolean; items: string[] }[];
  received_not_invoiced: { vendor: string; po: string; item_code: string; qty: string; rate: string; amount: string }[];
  received_not_invoiced_total: string;
  close_notes: { notes?: Record<string, string> };
  can_close: boolean; can_reopen: boolean;
}

function thisMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function ClosePage() {
  const [period, setPeriod] = useState(thisMonth());
  const { data, setData, error, loading } = useApi<Close>(`/close/${period}`);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [flux, setFlux] = useState<{ bullets: string[]; source: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(fn: () => Promise<Close>) {
    setActionError(null);
    try { setData(await fn()); } catch (e) { setActionError(e instanceof Error ? e.message : "Action failed."); }
  }

  return (
    <>
      <PageHeader title="Month-end close" description="Check the month, explain anything still open, and sign it off. Orrfin keeps no ledger: the accrual report is for your accountant."
                  actions={<Input aria-label="Month" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />} />
      <ErrorNotice message={error ?? actionError} />
      {loading ? <Loading /> : data ? (
        <div className="flex flex-col gap-6">
          {data.status === "closed" ? (
            <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
              <Lock className="size-4" aria-hidden /> {data.period} closed by {data.closed_by} on {formatDateTime(data.closed_at!)}. Approvals dated in it are refused.
            </p>
          ) : data.reopen_reason ? <p className="text-sm text-warning">Reopened: “{data.reopen_reason}”</p> : null}

          <Panel title="Checklist" actions={
            <span className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="tabular-nums">{data.checklist.filter((c) => c.ok).length} of {data.checklist.length} checks</span>
              <span aria-hidden className="h-1.5 w-24 overflow-hidden rounded-full bg-ice">
                <span className="block h-full rounded-full bg-brand-blue" style={{ width: `${(data.checklist.filter((c) => c.ok).length / Math.max(data.checklist.length, 1)) * 100}%` }} />
              </span>
            </span>
          }>
            <ul className="-my-1 divide-y divide-border/70">
              {data.checklist.map((c) => (
                <li key={c.key} className="py-3 text-sm">
                  <p className={`flex items-center gap-2 font-medium ${c.ok ? "text-success" : "text-[#8a5a12]"}`}>
                    {c.ok ? <CircleCheck className="size-4" aria-hidden /> : <TriangleAlert className="size-4" aria-hidden />}
                    {c.label}{c.ok ? "" : ` · ${c.open} open`}
                  </p>
                  {c.items.length ? <p className="pl-6 text-xs text-muted-foreground">{c.items.join(", ")}</p> : null}
                  {!c.ok && data.can_close ? (
                    <Input aria-label={`Why close with this open: ${c.label}`} className="mt-1 ml-6 w-[calc(100%-1.5rem)]" placeholder="Why it is fine to close anyway"
                           value={notes[c.key] ?? ""} onChange={(e) => setNotes({ ...notes, [c.key]: e.target.value })} />
                  ) : null}
                  {data.close_notes.notes?.[c.key] ? <p className="pl-6 text-xs">Closed with note: “{data.close_notes.notes[c.key]}”</p> : null}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title={`Received, not yet invoiced · ${formatINR(data.received_not_invoiced_total)}`}
                 actions={<a href={`/api/close/${data.period}/received-not-invoiced.csv`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline"><Download className="size-4" aria-hidden /> CSV</a>}>
            {data.received_not_invoiced.length ? (
              <div className="-mx-4 overflow-x-auto border-y border-border"><table className={table.table}>
                <thead><tr>{["Vendor", "PO", "Item", "Qty", "PO rate", "Amount"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
                <tbody>{data.received_not_invoiced.map((r) => (
                  <tr key={`${r.po}-${r.item_code}`}>
                    <td className={table.td}>{r.vendor}</td><td className={table.td}>{r.po}</td><td className={table.td}>{r.item_code}</td>
                    <td className={`${table.td} ${table.num}`}>{formatQty(r.qty)}</td>
                    <td className={`${table.td} ${table.num}`}>{formatINR(r.rate)}</td>
                    <td className={`${table.td} ${table.num}`}>{formatINR(r.amount)}</td>
                  </tr>))}</tbody>
              </table></div>
            ) : <p className="text-sm text-muted-foreground">Everything received this month has been invoiced.</p>}
            <p className="mt-2 text-xs text-muted-foreground">A report for your accountant&apos;s accrual. Orrfin writes no journal entries.</p>
          </Panel>

          <Panel title="What changed this month" actions={<Button size="sm" variant="outline" onClick={() => void post<{ bullets: string[]; source: string }>("/insights/notes?period=month").then(setFlux).catch(() => setActionError("Could not explain."))}>Explain</Button>}>
            {flux ? <ul className="list-disc pl-5 text-sm">{flux.bullets.map((b) => <li key={b}>{b}</li>)}</ul> : <p className="text-sm text-muted-foreground">Compares this month with last month, from Orrfin&apos;s numbers.</p>}
          </Panel>

          {data.can_close ? <Button size="lg" className="self-start" onClick={() => void act(() => post<Close>(`/close/${data.period}/close`, { notes }))}><Lock aria-hidden /> Close {data.period}</Button> : null}
          {data.can_reopen ? (
            <Panel title="Reopen (admin)">
              <Textarea aria-label="Reason to reopen" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button className="mt-2" variant="outline" disabled={!reason.trim()} onClick={() => void act(() => post<Close>(`/close/${data.period}/reopen`, { reason }))}>Reopen {data.period}</Button>
            </Panel>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
