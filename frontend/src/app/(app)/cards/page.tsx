"use client";

/**
 * Vendor cards (BUILD_PLAN change 46, ADR 0008). Every card here is SIMULATED: no card number
 * exists and no money can move. Finance or an admin issues a card for an approved request; the
 * holder can try a charge (to see the rules work) and freeze the card. The server enforces all of it.
 */
import { useState } from "react";
import { CreditCard, Snowflake } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { post, put } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Card {
  id: string; last4: string; currency: string; limit: string; spent: string; available: string; merchant_lock: string | null;
  expires_on: string; status: string; request_id: string; request_label: string; notice: string;
  transactions: { id: string; merchant: string; amount: string; status: string; decline_reason: string | null; at: string }[];
}

export default function CardsPage() {
  const me = useMe();
  const cards = useApi<Card[]>("/cards");
  const requests = useApi<{ id: string; number: number; title: string; status: string }[]>(me.role === "finance" || me.role === "admin" ? "/requests" : null);
  const [issue, setIssue] = useState({ request_id: "", limit: "", days: "30", merchant_lock: "" });
  const [charge, setCharge] = useState<Record<string, { merchant: string; amount: string }>>({});
  const [error, setError] = useState<string | null>(null);

  if (cards.loading) return <Loading />;
  if (cards.error) return <ErrorNotice message={cards.error} />;
  const issuer = me.role === "finance" || me.role === "admin";
  const approved = (requests.data ?? []).filter((r) => ["approved", "po_drafted", "po_open"].includes(r.status));

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); await cards.reload(); } catch (e) { setError(e instanceof Error ? e.message : "That did not work."); }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Vendor cards" description="Single-purpose virtual cards for an approved request. Simulated: no real card or money is involved." />
      <ErrorNotice message={error} />
      {issuer ? (
        <Panel title="Issue a card">
          <div className="grid items-end gap-3 p-4 sm:grid-cols-5">
            <Field label="Approved request" htmlFor="c-req" className="sm:col-span-2">
              <select id="c-req" className="h-9 rounded-lg border border-border px-2 text-sm" value={issue.request_id} onChange={(e) => setIssue({ ...issue, request_id: e.target.value })}>
                <option value="">Choose…</option>{approved.map((r) => <option key={r.id} value={r.id}>PR-{String(r.number).padStart(4, "0")} {r.title}</option>)}
              </select>
            </Field>
            <Field label="Limit" htmlFor="c-limit"><Input id="c-limit" inputMode="decimal" value={issue.limit} onChange={(e) => setIssue({ ...issue, limit: e.target.value })} /></Field>
            <Field label="Only at merchant (optional)" htmlFor="c-lock"><Input id="c-lock" value={issue.merchant_lock} onChange={(e) => setIssue({ ...issue, merchant_lock: e.target.value })} /></Field>
            <Button disabled={!issue.request_id || !issue.limit} onClick={() => run(() => post("/cards", { ...issue, days: Number(issue.days), merchant_lock: issue.merchant_lock || null }))}><CreditCard aria-hidden /> Issue</Button>
          </div>
        </Panel>
      ) : null}
      {(cards.data ?? []).length === 0 ? <EmptyState>No cards yet.</EmptyState> : cards.data?.map((c) => (
        <Panel key={c.id} title={`•••• ${c.last4} · ${c.request_label} · ${c.status}`}>
          <div className="space-y-3 p-4 text-sm">
            <p className="font-medium text-warning">{c.notice}</p>
            <p>{c.currency} {c.spent} spent of {c.limit} ({c.available} left) · expires {formatDate(c.expires_on)}{c.merchant_lock ? ` · only at ${c.merchant_lock}` : ""}</p>
            {c.status !== "closed" ? (
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Try a charge: merchant" htmlFor={`m-${c.id}`}><Input id={`m-${c.id}`} value={charge[c.id]?.merchant ?? ""} onChange={(e) => setCharge({ ...charge, [c.id]: { ...(charge[c.id] ?? { amount: "" }), merchant: e.target.value } })} /></Field>
                <Field label="Amount" htmlFor={`a-${c.id}`}><Input id={`a-${c.id}`} inputMode="decimal" value={charge[c.id]?.amount ?? ""} onChange={(e) => setCharge({ ...charge, [c.id]: { ...(charge[c.id] ?? { merchant: "" }), amount: e.target.value } })} /></Field>
                <Button variant="outline" onClick={() => run(() => post(`/cards/${c.id}/simulate-charge`, charge[c.id]))}>Simulate charge</Button>
                {c.status === "active" ? <Button variant="outline" onClick={() => run(() => put(`/cards/${c.id}/status`, { status: "frozen" }))}><Snowflake aria-hidden /> Freeze</Button> : null}
                {issuer && c.status === "frozen" ? <Button variant="outline" onClick={() => run(() => put(`/cards/${c.id}/status`, { status: "active" }))}>Unfreeze</Button> : null}
                {issuer ? <Button variant="outline" onClick={() => run(() => put(`/cards/${c.id}/status`, { status: "closed" }))}>Close</Button> : null}
              </div>
            ) : null}
            {c.transactions.length > 0 ? (
              <ul className="space-y-1">{c.transactions.map((t) => (
                <li key={t.id}>{formatDateTime(t.at)} · {t.merchant} · {c.currency} {t.amount} · {t.status}{t.decline_reason ? `: ${t.decline_reason}` : ""}</li>
              ))}</ul>
            ) : null}
          </div>
        </Panel>
      ))}
    </div>
  );
}
