"use client";

/**
 * One RFQ (BUILD_PLAN §6f): invite suppliers, open, and after closing the side-by-side comparison
 * with its arithmetic. Quotes stay sealed until close. The award raises a normal draft request.
 */
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Lock, Trophy } from "lucide-react";

import { AsideCard, BackLink, DetailLayout } from "@/components/detail";
import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { MetaList, PersonCell, StatusPill } from "@/components/ui/display";
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
    <>
      <PageHeader meta={<BackLink href="/sourcing" label="Sourcing" />} title={`${r.number} · ${r.title}`}
                  description={`Quotes close ${formatDateTime(r.closes_at)} · ${r.currency}`}
                  actions={
                    <span className="flex items-center gap-2">
                      <StatusPill tone={r.status === "open" ? "info" : r.status === "awarded" ? "success" : r.status === "cancelled" ? "muted" : "neutral"}>
                        <span className="capitalize">{r.status}</span>
                      </StatusPill>
                      {r.status === "draft" ? <Button onClick={() => act("open")}>Open for quotes</Button> : null}
                      {r.status === "open" ? <Button variant="outline" onClick={() => act("close")}>Close now</Button> : null}
                    </span>
                  } />
      <DetailLayout
        aside={
          <>
            <AsideCard title="What is being bought">
              <MetaList rows={r.lines.map((l) => ({ label: l.description, value: `${l.qty} ${l.uom}` }))} />
              <p className="mt-3 text-xs font-medium text-heading">Scoring weights (fixed once open)</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(r.weights).map(([k, v]) => (
                  <span key={k} className="rounded-md bg-ice px-2 py-0.5 text-xs capitalize text-heading">{k.replace("_", " ")} {v}</span>
                ))}
              </div>
            </AsideCard>
            <AsideCard title={`Invited suppliers · ${r.invited.length}`}>
              <ul className="space-y-2 py-1">
                {r.invited.map((sup) => <li key={sup.id}><PersonCell name={sup.legal_name} size="xs" /></li>)}
                {r.invited.length === 0 ? <li className="text-sm text-muted-foreground">Nobody invited yet.</li> : null}
              </ul>
              {r.status === "draft" || r.status === "open" ? (
                <div className="mt-3 flex items-end gap-2 border-t border-border pt-3">
                  <Field label="Invite an approved supplier" htmlFor="pick" className="flex-1">
                    <Select id="pick" value={pick} onChange={(e) => setPick(e.target.value)}>
                      <option value="">Choose…</option>{invitable.map((sup) => <option key={sup.id} value={sup.id}>{sup.legal_name}</option>)}
                    </Select>
                  </Field>
                  <Button variant="outline" disabled={!pick} onClick={() => act("invites", { supplier_ids: [pick] })}>Invite</Button>
                </div>
              ) : null}
            </AsideCard>
          </>
        }
        main={
          <>
            <ErrorNotice message={error} />
            {r.request_id ? (
              <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm text-success">
                <Trophy className="size-4" aria-hidden />
                <span>Awarded. The purchase request is <Link className="font-medium underline" href={`/requests/${r.request_id}`}>here</Link>; it goes through the normal approvals before any order.</span>
              </p>
            ) : null}
            {r.comparison === null ? (
              <div className="rounded-xl border border-dashed border-border bg-white px-6 py-12 text-center">
                <Lock className="mx-auto size-6 text-muted-foreground" aria-hidden />
                <p className="mt-3 font-medium text-heading">Quotes are sealed</p>
                <p className="mt-1 text-sm text-muted-foreground">They open when the RFQ closes. Not even their number is shown before then.</p>
              </div>
            ) : (
              <Panel title="Comparison · best score first">
                <div className="-m-4 overflow-x-auto">
                  <table className={table.table}>
                    <thead><tr>{["Supplier", `Landed cost (${r.currency})`, "Delivery", "Terms", "Score", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
                    <tbody>{r.comparison.map((q, i) => (
                      <tr key={q.quote_id} className={i === 0 ? "bg-success/5" : undefined}>
                        <td className={`${table.td} font-medium`}>
                          <span className="flex items-center gap-1.5">{i === 0 && q.score ? <Trophy className="size-3.5 text-success" aria-label="Best score" /> : null}{q.supplier_name}</span>
                          {q.note ? <p className="text-xs font-normal text-muted-foreground">{q.note}</p> : null}
                        </td>
                        <td className={`${table.td} ${table.num}`}>{q.landed_cost ?? "–"}</td>
                        <td className={table.td}>{q.delivery_days} days</td><td className={table.td}>{q.payment_terms_days} days</td>
                        <td className={table.td}><span className="font-semibold">{q.score ?? "not scored"}</span>
                          <ul className="text-xs text-muted-foreground">{Object.entries(q.arithmetic ?? {}).map(([k, v]) => <li key={k}>{k.replace("_", " ")}: {v}</li>)}</ul></td>
                        <td className={table.td}>{r.status === "closed" && q.score ? <Button size="sm" variant={i === 0 ? "default" : "outline"} onClick={() => setAward({ quote_id: q.quote_id, reason: "" })}>Award</Button> : null}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
                {award ? (
                  <div className="mt-8 space-y-2 border-t border-border pt-4">
                    <Field label="Reason (required when this is not the top score)" htmlFor="award-reason"><Textarea id="award-reason" value={award.reason} onChange={(e) => setAward({ ...award, reason: e.target.value })} /></Field>
                    <Button onClick={() => act("award", award)}>Confirm award and raise the purchase request</Button>
                  </div>
                ) : null}
              </Panel>
            )}
          </>
        }
      />
    </>
  );
}
