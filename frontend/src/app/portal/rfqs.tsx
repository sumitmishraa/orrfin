"use client";

/**
 * Supplier portal: RFQs this supplier was invited to, and its own sealed quote (BUILD_PLAN §6f).
 * The server shows only this supplier's own quote and refuses changes once the RFQ closes.
 */
import { useEffect, useState } from "react";

import { ErrorNotice, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { portalApi } from "@/lib/portal-api";

interface PortalRfq {
  id: string; number: string; title: string; currency: string; closes_at: string; status: string; weights: Record<string, number>;
  lines: { id: string; description: string; qty: string; uom: string; rate: string | null; tax_rate: string | null }[];
  my_quote: { currency: string; freight: string; payment_terms_days: number; delivery_days: number; valid_until: string } | null;
}

function QuoteForm({ rfq, onSaved }: { rfq: PortalRfq; onSaved: (rows: PortalRfq[]) => void }) {
  const [head, setHead] = useState({ currency: rfq.my_quote?.currency ?? rfq.currency, freight: rfq.my_quote?.freight ?? "0",
    payment_terms_days: String(rfq.my_quote?.payment_terms_days ?? 30), delivery_days: String(rfq.my_quote?.delivery_days ?? 7),
    valid_until: rfq.my_quote?.valid_until ?? "" });
  const [lines, setLines] = useState(Object.fromEntries(rfq.lines.map((l) => [l.id, { rate: l.rate ?? "", tax_rate: l.tax_rate ?? "18" }])));
  const [error, setError] = useState<string | null>(null);
  const open = rfq.status === "open";

  async function save() {
    setError(null);
    try {
      onSaved(await portalApi<PortalRfq[]>(`/portal/rfqs/${rfq.id}/quote`, { method: "PUT", body: JSON.stringify({
        ...head, payment_terms_days: Number(head.payment_terms_days), delivery_days: Number(head.delivery_days),
        lines: Object.entries(lines).map(([rfq_line_id, v]) => ({ rfq_line_id, ...v })) }) }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the quote.");
    }
  }

  return (
    <Panel title={`${rfq.number}: ${rfq.title} (${rfq.status}, closes ${new Date(rfq.closes_at).toLocaleString()})`}>
      <div className="space-y-3 p-4 text-sm">
        <ErrorNotice message={error} />
        <p className="text-muted-foreground">How quotes are scored: {Object.entries(rfq.weights).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(", ")}. Your quote is sealed until the RFQ closes.</p>
        {rfq.lines.map((l) => (
          <div key={l.id} className="grid items-end gap-2 sm:grid-cols-[1fr_8rem_6rem]">
            <span>{l.description} ({l.qty} {l.uom})</span>
            <Field label="Unit rate" htmlFor={`r-${l.id}`}><Input id={`r-${l.id}`} disabled={!open} inputMode="decimal" value={lines[l.id].rate} onChange={(e) => setLines({ ...lines, [l.id]: { ...lines[l.id], rate: e.target.value } })} /></Field>
            <Field label="Tax %" htmlFor={`t-${l.id}`}><Input id={`t-${l.id}`} disabled={!open} inputMode="decimal" value={lines[l.id].tax_rate} onChange={(e) => setLines({ ...lines, [l.id]: { ...lines[l.id], tax_rate: e.target.value } })} /></Field>
          </div>
        ))}
        <div className="grid gap-2 sm:grid-cols-5">
          <Field label="Currency" htmlFor={`c-${rfq.id}`}><Select id={`c-${rfq.id}`} disabled={!open} value={head.currency} onChange={(e) => setHead({ ...head, currency: e.target.value })}>{["INR", "AED", "USD", "EUR"].map((c) => <option key={c}>{c}</option>)}</Select></Field>
          <Field label="Freight" htmlFor={`f-${rfq.id}`}><Input id={`f-${rfq.id}`} disabled={!open} value={head.freight} onChange={(e) => setHead({ ...head, freight: e.target.value })} /></Field>
          <Field label="Payment terms (days)" htmlFor={`p-${rfq.id}`}><Input id={`p-${rfq.id}`} disabled={!open} value={head.payment_terms_days} onChange={(e) => setHead({ ...head, payment_terms_days: e.target.value })} /></Field>
          <Field label="Delivery (days)" htmlFor={`d-${rfq.id}`}><Input id={`d-${rfq.id}`} disabled={!open} value={head.delivery_days} onChange={(e) => setHead({ ...head, delivery_days: e.target.value })} /></Field>
          <Field label="Valid until" htmlFor={`v-${rfq.id}`}><Input id={`v-${rfq.id}`} type="date" disabled={!open} value={head.valid_until} onChange={(e) => setHead({ ...head, valid_until: e.target.value })} /></Field>
        </div>
        {open ? <Button onClick={save}>{rfq.my_quote ? "Update my quote" : "Send my quote"}</Button> : null}
      </div>
    </Panel>
  );
}

export function PortalRfqs() {
  const [rows, setRows] = useState<PortalRfq[] | null>(null);
  useEffect(() => {
    portalApi<PortalRfq[]>("/portal/rfqs").then(setRows).catch(() => setRows([]));
  }, []);
  if (!rows || rows.length === 0) return null;
  return <section className="space-y-4"><h2 className="font-display text-xl font-semibold text-heading">Requests for quotation</h2>{rows.map((r) => <QuoteForm key={r.id} rfq={r} onSaved={setRows} />)}</section>;
}
