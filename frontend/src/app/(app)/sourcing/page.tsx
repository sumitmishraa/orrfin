"use client";

/**
 * Sourcing (BUILD_PLAN change 43, §6f): RFQs and a form to start one. The scoring weights are
 * shown and fixed when the RFQ opens; the server refuses weights that do not add up to 100.
 */
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Category } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { useRouter } from "next/navigation";

interface RfqRow { id: string; number: string; title: string; status: string; closes_at: string; currency: string }
const WEIGHTS = { price: 60, delivery: 20, payment_terms: 10, supplier_risk: 10 };

export default function SourcingPage() {
  const me = useMe();
  const router = useRouter();
  const rfqs = useApi<RfqRow[]>("/rfqs");
  const categories = useApi<Category[]>("/categories");
  const [form, setForm] = useState<{ title: string; category_id: string; currency: string; closes_at: string; lines: { description: string; qty: string }[]; weights: typeof WEIGHTS } | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (rfqs.loading) return <Loading />;
  if (rfqs.error) return <ErrorNotice message={rfqs.error} />;
  const canCreate = ["buyer", "finance", "admin"].includes(me.role);
  const total = form ? Object.values(form.weights).reduce((a, b) => a + b, 0) : 100;

  async function create() {
    if (!form) return;
    setError(null);
    try {
      const created = await post<{ id: string }>("/rfqs", { ...form, closes_at: new Date(form.closes_at).toISOString() });
      router.push(`/sourcing/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the RFQ.");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Sourcing" description="Ask approved suppliers for sealed quotes, compare them side by side and award one."
        actions={canCreate && !form ? <Button onClick={() => setForm({ title: "", category_id: "", currency: "INR", closes_at: "", lines: [{ description: "", qty: "1" }], weights: { ...WEIGHTS } })}><Plus aria-hidden /> New RFQ</Button> : undefined} />
      <ErrorNotice message={error} />
      {form ? (
        <Panel title="New request for quotation">
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Title" htmlFor="rfq-title"><Input id="rfq-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label="Category" htmlFor="rfq-cat">
              <Select id="rfq-cat" value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
                <option value="">Choose…</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="Currency" htmlFor="rfq-cur">
              <Select id="rfq-cur" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                {["INR", "AED", "USD", "EUR"].map((c) => <option key={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Quotes close at" htmlFor="rfq-close"><Input id="rfq-close" type="datetime-local" value={form.closes_at} onChange={(e) => setForm({ ...form, closes_at: e.target.value })} /></Field>
            {form.lines.map((line, i) => (
              <div key={i} className="grid grid-cols-[1fr_7rem] gap-3 sm:col-span-2">
                <Field label={`Line ${i + 1}`} htmlFor={`rfq-l-${i}`}><Input id={`rfq-l-${i}`} value={line.description} onChange={(e) => setForm({ ...form, lines: form.lines.map((l, n) => n === i ? { ...l, description: e.target.value } : l) })} /></Field>
                <Field label="Qty" htmlFor={`rfq-q-${i}`}><Input id={`rfq-q-${i}`} inputMode="decimal" value={line.qty} onChange={(e) => setForm({ ...form, lines: form.lines.map((l, n) => n === i ? { ...l, qty: e.target.value } : l) })} /></Field>
              </div>
            ))}
            <div className="sm:col-span-2"><Button variant="outline" size="sm" onClick={() => setForm({ ...form, lines: [...form.lines, { description: "", qty: "1" }] })}><Plus aria-hidden /> Add a line</Button></div>
            <fieldset className="grid grid-cols-2 gap-3 sm:col-span-2 sm:grid-cols-4">
              <legend className="mb-1 text-sm font-medium text-heading">Scoring weights (total {total}; must be 100, fixed once the RFQ opens)</legend>
              {(Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).map((k) => (
                <Field key={k} label={k.replace("_", " ")} htmlFor={`w-${k}`}>
                  <Input id={`w-${k}`} type="number" min={0} max={100} value={form.weights[k]} onChange={(e) => setForm({ ...form, weights: { ...form.weights, [k]: Number(e.target.value) } })} />
                </Field>
              ))}
            </fieldset>
            <div className="flex gap-2"><Button onClick={create} disabled={total !== 100 || !form.title || !form.category_id || !form.closes_at}>Create draft</Button><Button variant="outline" onClick={() => setForm(null)}>Cancel</Button></div>
          </div>
        </Panel>
      ) : null}
      {(rfqs.data ?? []).length === 0 ? <EmptyState>No RFQs yet.</EmptyState> : (
        <div className={table.wrap}><table className={table.table}>
          <thead><tr>{["RFQ", "Title", "Status", "Closes"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
          <tbody>{rfqs.data?.map((r) => (
            <tr key={r.id} className="border-t border-border">
              <td className="px-3 py-2.5"><Link href={`/sourcing/${r.id}`} className="font-medium text-heading hover:underline">{r.number}</Link></td>
              <td className="px-3 py-2.5">{r.title}</td><td className="px-3 py-2.5 capitalize">{r.status}</td>
              <td className="px-3 py-2.5">{formatDateTime(r.closes_at)}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}
