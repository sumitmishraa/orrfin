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
  categories: Category[];
  segregation_of_duties: Card[];
  matching: { rule_set_version: string; tolerances: Record<string, string>; rules: Card[] };
  [section: string]: unknown;
}

interface UserOption { id: string; full_name: string; role?: string }

interface Category {
  id: string; name: string; buyer_id: string | null; buyer_name: string | null;
  extra_approver_id: string | null; extra_approver_name: string | null; extra_step_label: string | null;
}

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

      <Panel title="Who completes each category, and any extra approval">
        <CategoryBuyers data={data} onChange={onChange} />
      </Panel>

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <Panel title="Reminders"><ReminderSettings /></Panel>
        <Panel title="Budgets this quarter"><BudgetsEditor /></Panel>
      </div>

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
            <ExtraStep category={c} canEdit={data.can_edit && me.role === "admin"} onChange={onChange} />
          </li>
        ))}
      </ul>
    </>
  );
}

/** Zip's conditional approver: a category can add one named step after the amount tiers. */
function ExtraStep({ category, canEdit, onChange }: { category: Category; canEdit: boolean; onChange: (d: RulesOverview) => void }) {
  const { data: people } = useApi<UserOption[]>(canEdit ? "/users" : null);
  const [approver, setApprover] = useState(category.extra_approver_id ?? "");
  const [label, setLabel] = useState(category.extra_step_label ?? "");
  const [error, setError] = useState<string | null>(null);

  async function save(body: Record<string, string | null>) {
    setError(null);
    try {
      onChange(await patch<RulesOverview>(`/rules/categories/${category.id}`, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  if (!canEdit) {
    return category.extra_approver_id ? (
      <p className="pl-[3.75rem] text-sm">+ then <b>{category.extra_step_label}</b> by {category.extra_approver_name}</p>
    ) : null;
  }
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-2 pl-[3.75rem]">
      <span className="text-xs text-muted-foreground">Extra approval step (after the amount tiers)</span>
      <div className="flex flex-wrap gap-2">
        <Input aria-label={`Extra step name for ${category.name}`} placeholder="e.g. IT security review" className="w-48"
               value={label} onChange={(e) => setLabel(e.target.value)} />
        <Select aria-label={`Extra approver for ${category.name}`} className="w-48" value={approver} onChange={(e) => setApprover(e.target.value)}>
          <option value="">No extra step</option>
          {(people ?? []).filter((p) => p.role !== "requester").map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
        </Select>
        <Button size="sm" variant="outline"
                onClick={() => void save(approver ? { extra_approver_id: approver, extra_step_label: label } : { extra_approver_id: null })}>
          Save step
        </Button>
      </div>
      <ErrorNotice message={error} />
    </div>
  );
}

function ReminderSettings() {
  const { data, setData, error } = useApi<{ approval_sla_hours: number; can_edit: boolean }>("/settings/workflow");
  const [value, setValue] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  if (!data) return <ErrorNotice message={error} />;
  const shown = value ?? String(data.approval_sla_hours);

  async function save() {
    setSaveError(null);
    try {
      setData(await put<{ approval_sla_hours: number; can_edit: boolean }>("/settings/workflow", { approval_sla_hours: Number(shown) }));
      setValue(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  return (
    <div className="flex flex-col gap-3 text-sm">
      <ul><IfThen card={{ if: `An approval step waits more than ${data.approval_sla_hours} hours`,
                          then: "It is marked overdue on My tasks and the dashboard; the requester, buyer or finance can nudge" }} /></ul>
      {data.can_edit ? (
        <div className="flex items-center gap-2">
          <Input aria-label="Overdue after (hours)" inputMode="numeric" className="w-24" value={shown} onChange={(e) => setValue(e.target.value)} />
          <span>hours</span>
          <Button size="sm" variant="outline" onClick={() => void save()}>Save</Button>
        </div>
      ) : null}
      <ErrorNotice message={saveError} />
    </div>
  );
}

interface BudgetRows {
  fiscal_year: string; quarter: number; can_edit: boolean;
  rows: { cost_center: string; budget: string; committed: string; invoiced: string; remaining: string; pct_used: string | null; over: boolean }[];
}

function BudgetsEditor() {
  const me = useMe();
  const { data, setData, error } = useApi<BudgetRows>(me.role === "requester" ? null : "/budgets");
  const [center, setCenter] = useState("");
  const [amount, setAmount] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  if (me.role === "requester") return <p className="text-sm text-muted-foreground">Your request form shows the budget for your cost centre.</p>;
  if (!data) return <ErrorNotice message={error} />;
  const period = data;

  async function save() {
    setSaveError(null);
    try {
      setData(await put<BudgetRows>("/budgets", { cost_center: center, fiscal_year: period.fiscal_year, quarter: period.quarter, amount }));
      setCenter("");
      setAmount("");
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-muted-foreground">{data.fiscal_year} Q{data.quarter}. A request that would go over its budget shows a warning to the requester and approvers; it is never blocked.</p>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="py-1">Cost centre</th><th className="text-right">Budget</th><th className="text-right">Committed</th><th className="text-right">Invoiced</th><th className="text-right">Used</th></tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.cost_center} className="border-t border-border">
                <td className="py-1.5 font-medium">{r.cost_center}</td>
                <td className="text-right tabular-nums">{formatINR(r.budget)}</td>
                <td className="text-right tabular-nums">{formatINR(r.committed)}</td>
                <td className="text-right tabular-nums">{formatINR(r.invoiced)}</td>
                <td className={`text-right tabular-nums ${r.over ? "font-semibold text-error" : ""}`}>{r.pct_used ? `${r.pct_used}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.can_edit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Cost centre" placeholder="Cost centre, e.g. IT-OPS" className="w-44" value={center} onChange={(e) => setCenter(e.target.value)} />
          <Input aria-label="Budget amount" inputMode="decimal" placeholder="Amount, e.g. 500000.00" className="w-44" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Button size="sm" variant="outline" disabled={!center.trim() || !amount.trim()} onClick={() => void save()}>Set budget</Button>
        </div>
      ) : null}
      <ErrorNotice message={saveError} />
    </div>
  );
}
