"use client";

/**
 * Rules: every control as an IF/THEN card (BUILD_PLAN v2.3 change 24; PROMPTS Step 21).
 * Everyone can read. Admins edit the approval tiers and which buyer owns each category; the
 * server validates and audits each change, and tier changes apply to new approval chains only.
 * Segregation of duties and the matching rules are fixed in code and shown read-only.
 */
import { useState } from "react";
import { Lock, Plus, Trash2 } from "lucide-react";

import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { patch, put } from "@/lib/api";
import { formatINR, ROLE_LABELS } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Tier { min_amount: string; max_amount: string | null; steps: string[] }
interface Card { if: string; then: string }

export interface RulesOverview {
  can_edit: boolean;
  step_roles: string[];
  approval_tiers: Tier[];
  categories: { id: string; name: string; buyer_id: string | null; buyer_name: string | null }[];
  segregation_of_duties: Card[];
  matching: { rule_set_version: string; tolerances: Record<string, string>; rules: Card[] };
  [section: string]: unknown;
}

interface UserOption { id: string; full_name: string }

function IfThen({ card, tone = "navy" }: { card: Card; tone?: "navy" | "locked" }) {
  return (
    <li className="grid gap-1.5 rounded-xl border border-border bg-white p-3 text-sm">
      <div className="grid grid-cols-[3.25rem_1fr] items-baseline gap-2">
        <span className="rounded bg-ice px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold text-heading">IF</span>
        <span>{card.if}</span>
      </div>
      <div className="grid grid-cols-[3.25rem_1fr] items-baseline gap-2">
        <span className={`rounded px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold ${tone === "navy" ? "bg-navy text-white" : "bg-muted text-muted-foreground"}`}>THEN</span>
        <span className="font-medium">{card.then}</span>
      </div>
    </li>
  );
}

function tierCard(tier: Tier): Card {
  const range = tier.max_amount !== null ? `${formatINR(tier.min_amount)} – ${formatINR(tier.max_amount)}`
    : tier.min_amount === "0.00" ? "any amount" : `${formatINR(tier.min_amount)} or more`;
  return { if: `A request is ${range}`, then: tier.steps.map((s) => ROLE_LABELS[s] ?? s).join(" → ") };
}

export default function RulesPage() {
  const { data, error, loading, setData } = useApi<RulesOverview>("/rules");
  return (
    <>
      <PageHeader title="Rules" description="Every control Orrfin enforces, in plain words. Admins can change approvals and buyers." />
      <ErrorNotice message={error} />
      {loading && !data ? <Loading /> : data ? <Rules data={data} onChange={setData} /> : null}
    </>
  );
}

function Rules({ data, onChange }: { data: RulesOverview; onChange: (d: RulesOverview) => void }) {
  return (
    <div className="flex flex-col gap-6">
      <Panel title="Approval chain by amount">
        {data.can_edit ? <TierEditor data={data} onChange={onChange} /> : (
          <ul className="grid gap-3 md:grid-cols-2">{data.approval_tiers.map((t) => <IfThen key={t.min_amount} card={tierCard(t)} />)}</ul>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          A change applies to requests that start approval after it. Requests already in approval keep their chain.
        </p>
      </Panel>

      <Panel title="Who completes each category">
        <CategoryBuyers data={data} onChange={onChange} />
      </Panel>

      <Panel title="Segregation of duties" actions={<Locked />}>
        <ul className="grid gap-3 md:grid-cols-2">{data.segregation_of_duties.map((c) => <IfThen key={c.if} card={c} tone="locked" />)}</ul>
      </Panel>

      <Panel title={`Invoice matching rules · version ${data.matching.rule_set_version}`} actions={<Locked />}>
        <ul className="grid gap-3 md:grid-cols-2">{data.matching.rules.map((c) => <IfThen key={c.if} card={c} tone="locked" />)}</ul>
        <p className="mt-3 text-xs text-muted-foreground">
          Tolerances change only through a reviewed release (to be confirmed by a CA). Every match result stores the version and tolerances it used.
        </p>
      </Panel>
    </div>
  );
}

function Locked() {
  return <span className="flex items-center gap-1 text-xs text-muted-foreground"><Lock className="size-3.5" aria-hidden /> Fixed in code</span>;
}

/** Admins edit only where each tier ends; each next tier starts one paisa later, so gaps can't happen. */
function TierEditor({ data, onChange }: { data: RulesOverview; onChange: (d: RulesOverview) => void }) {
  const [tiers, setTiers] = useState<Tier[]>(data.approval_tiers);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const withStarts = (list: Tier[]): Tier[] => list.map((t, i) => ({
    ...t,
    min_amount: i === 0 ? "0.00" : nextPaisa(list[i - 1].max_amount ?? "0"),
    max_amount: i === list.length - 1 ? null : t.max_amount,
  }));
  const update = (i: number, change: Partial<Tier>) => {
    setSaved(false);
    setTiers((list) => withStarts(list.map((t, j) => (j === i ? { ...t, ...change } : t))));
  };
  const toggleStep = (i: number, role: string) => {
    const steps = tiers[i].steps.includes(role) ? tiers[i].steps.filter((s) => s !== role)
      : data.step_roles.filter((r) => r === role || tiers[i].steps.includes(r)); // keep the fixed order
    update(i, { steps });
  };

  async function save() {
    setBusy(true); setError(null);
    try {
      onChange(await put<RulesOverview>("/rules/approval-tiers", { tiers }));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {tiers.map((tier, i) => (
        <div key={i} className="grid items-center gap-3 rounded-xl border border-border p-3 md:grid-cols-[14rem_1fr_2.5rem]">
          <div className="flex items-center gap-2 text-sm">
            <span className="tabular-nums">{formatINR(tier.min_amount)} to</span>
            {i === tiers.length - 1 ? <span className="font-medium">any amount</span> : (
              <Input aria-label={`Tier ${i + 1} ends at`} inputMode="decimal" className="w-32"
                     value={tier.max_amount ?? ""} onChange={(e) => update(i, { max_amount: e.target.value })} />
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {data.step_roles.map((role) => (
              <label key={role} className="flex items-center gap-1.5">
                <input type="checkbox" checked={tier.steps.includes(role)} onChange={() => toggleStep(i, role)} />
                {ROLE_LABELS[role] ?? role}
              </label>
            ))}
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove tier ${i + 1}`} disabled={tiers.length === 1}
                  onClick={() => { setSaved(false); setTiers((list) => withStarts(list.filter((_, j) => j !== i))); }}>
            <Trash2 aria-hidden />
          </Button>
        </div>
      ))}
      <ErrorNotice message={error} />
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => {
          setSaved(false);
          setTiers((list) => withStarts([...list.slice(0, -1),
            { ...list[list.length - 1], max_amount: "" }, { min_amount: "0", max_amount: null, steps: ["manager", "finance", "admin"] }]));
        }}><Plus aria-hidden /> Add a tier</Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => void save()}>Save approval tiers</Button>
        {saved ? <span className="text-sm text-success">Saved and recorded in the audit trail.</span> : null}
      </div>
    </div>
  );
}

/** "50000" or "50000.00" → "50000.01", in exact decimal arithmetic (no float). */
function nextPaisa(value: string): string {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return value;
  const [whole, fraction = ""] = value.split(".");
  const paise = BigInt(whole + (fraction + "00").slice(0, 2)) + BigInt(1);
  const text = paise.toString().padStart(3, "0");
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}

function CategoryBuyers({ data, onChange }: { data: RulesOverview; onChange: (d: RulesOverview) => void }) {
  const me = useMe();
  const { data: buyers } = useApi<UserOption[]>(data.can_edit ? "/users?role=buyer" : null);
  const [error, setError] = useState<string | null>(null);

  async function setBuyer(categoryId: string, buyerId: string) {
    setError(null);
    try {
      onChange(await patch<RulesOverview>(`/rules/categories/${categoryId}`, { buyer_id: buyerId || null }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  return (
    <>
      <ErrorNotice message={error} />
      <ul className="grid gap-3 md:grid-cols-2">
        {data.categories.map((c) => (
          <li key={c.id} className="grid gap-1.5 rounded-xl border border-border p-3 text-sm">
            <div className="grid grid-cols-[3.25rem_1fr] items-baseline gap-2">
              <span className="rounded bg-ice px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold text-heading">IF</span>
              <span>A request is for <b>{c.name}</b></span>
            </div>
            <div className="grid grid-cols-[3.25rem_1fr] items-center gap-2">
              <span className="rounded bg-navy px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold text-white">THEN</span>
              {data.can_edit && me.role === "admin" ? (
                <Select aria-label={`Buyer for ${c.name}`} value={c.buyer_id ?? ""} onChange={(e) => void setBuyer(c.id, e.target.value)}>
                  <option value="">No buyer: the admin queue handles it</option>
                  {(buyers ?? []).map((b) => <option key={b.id} value={b.id}>{b.full_name} completes it</option>)}
                </Select>
              ) : <span className="font-medium">{c.buyer_name ? `${c.buyer_name} completes it` : "The admin queue handles it"}</span>}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
