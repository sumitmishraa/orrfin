"use client";

/**
 * One RFQ (BUILD_PLAN §6f): invite suppliers, open, and after closing the side-by-side comparison
 * with its arithmetic. Quotes stay sealed until close. The award raises a normal draft request.
 */
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Row {
  quote_id: string; supplier_name: string; currency: string; landed_cost: string | null; converted: boolean;
  delivery_days: number; payment_terms_days: number; score: string | null; arithmetic: Record<string, string>; note: string | null;
}
interface Rfq {
  id: string; number: string; title: string; currency: string; status: string; closes_at: string; request_id: string | null;
  weights: Record<string, number>; lines: { id: string; description: string; qty: string; uom: string }[];
  invited: { id: string; legal_name: string }[]; comparison: Row[] | null;
}

export default function RfqPage() {
  const { id } = useParams<{ id: string }>();
  const rfq = useApi<Rfq>(`/rfqs/${id}`);
  const suppliers = useApi<{ id: string; legal_name: string; status: string; on_hold: boolean }[]>("/suppliers");
  const [pick, setPick] = useState("");
  const [award, setAward] = useState<{ quote_id: string; reason: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (rfq.loading) return <Loading />;
  if (rfq.error || !rfq.data) return <ErrorNotice message={rfq.error ?? "RFQ not found."} />;
  const r = rfq.data;

  async function act(path: string, body?: unknown) {
    setError(null);
    try {
      rfq.setData(await post<Rfq>(`/rfqs/${id}/${path}`, body));
      setAward(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    }
  }
  const invitable = (suppliers.data ?? []).filter((s) => ["approved", "handed_over", "active"].includes(s.status) && !s.on_hold && !r.invited.some((i) => i.id === s.id));

  return (
    <div className="space-y-6">
      <PageHeader title={`${r.number}: ${r.title}`} description={`${r.status} · closes ${formatDateTime(r.closes_at)} · ${r.currency}`} />
      <ErrorNotice message={error} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="What is being bought">
          <ul className="space-y-1 p-4 text-sm">{r.lines.map((l) => <li key={l.id}>{l.description}: {l.qty} {l.uom}</li>)}</ul>
          <p className="px-4 pb-4 text-xs text-muted-foreground">Scoring: {Object.entries(r.weights).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}</p>
        </Panel>
        <Panel title={`Invited suppliers (${r.invited.length})`}>
          <div className="space-y-3 p-4 text-sm">
            <ul>{r.invited.map((s) => <li key={s.id}>{s.legal_name}</li>)}</ul>
            {r.status === "draft" || r.status === "open" ? (
              <div className="flex items-end gap-2">
                <Field label="Invite an approved supplier" htmlFor="pick" className="flex-1">
                  <Select id="pick" value={pick} onChange={(e) => setPick(e.target.value)}>
                    <option value="">Choose…</option>{invitable.map((s) => <option key={s.id} value={s.id}>{s.legal_name}</option>)}
                  </Select>
                </Field>
                <Button variant="outline" disabled={!pick} onClick={() => act("invites", { supplier_ids: [pick] })}>Invite</Button>
              </div>
            ) : null}
            {r.status === "draft" ? <Button onClick={() => act("open")}>Open for quotes</Button> : null}
            {r.status === "open" ? <Button variant="outline" onClick={() => act("close")}>Close now</Button> : null}
          </div>
        </Panel>
      </div>
      {r.comparison === null ? (
        <p className="text-sm text-muted-foreground">Quotes are sealed until the RFQ closes. Not even their number is shown before then.</p>
      ) : (
        <Panel title="Comparison (best score first)">
          <div className={table.wrap}><table className={table.table}>
            <thead><tr>{["Supplier", `Landed cost (${r.currency})`, "Delivery", "Terms", "Score", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
            <tbody>{r.comparison.map((q, i) => (
              <tr key={q.quote_id} className="border-t border-border align-top">
                <td className="px-3 py-2.5 font-medium">{q.supplier_name}{q.note ? <p className="text-xs font-normal text-muted-foreground">{q.note}</p> : null}</td>
                <td className="px-3 py-2.5 tabular-nums">{q.landed_cost ?? "–"}</td>
                <td className="px-3 py-2.5">{q.delivery_days} days</td><td className="px-3 py-2.5">{q.payment_terms_days} days</td>
                <td className="px-3 py-2.5"><span className="font-semibold">{q.score ?? "not scored"}</span>
                  <ul className="text-xs text-muted-foreground">{Object.entries(q.arithmetic ?? {}).map(([k, v]) => <li key={k}>{k.replace("_", " ")}: {v}</li>)}</ul></td>
                <td className="px-3 py-2.5">{r.status === "closed" && q.score ? <Button size="sm" variant={i === 0 ? "default" : "outline"} onClick={() => setAward({ quote_id: q.quote_id, reason: "" })}>Award</Button> : null}</td>
              </tr>))}</tbody>
          </table></div>
          {award ? (
            <div className="space-y-2 p-4">
              <Field label="Reason (required when this is not the top score)" htmlFor="award-reason"><Textarea id="award-reason" value={award.reason} onChange={(e) => setAward({ ...award, reason: e.target.value })} /></Field>
              <Button onClick={() => act("award", award)}>Confirm award and raise the purchase request</Button>
            </div>
          ) : null}
        </Panel>
      )}
      {r.request_id ? <p className="text-sm">Awarded. The purchase request is <Link className="font-medium text-primary underline" href={`/requests/${r.request_id}`}>here</Link>; it goes through the normal approvals before any order.</p> : null}
    </div>
  );
}
