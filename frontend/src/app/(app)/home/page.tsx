"use client";

/**
 * Home: the control dashboard (BUILD_PLAN v2.3 change 23; PROMPTS Step 21).
 * Every number comes from GET /insights/summary, computed by rules on the server, never by AI.
 * Requesters see their own requests only; everyone else also sees invoices, spend and ERP drafts.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, ChevronRight, Plus, X } from "lucide-react";

import { useMe } from "@/components/session";
import { Button, buttonVariants } from "@/components/ui/button";
import { post } from "@/lib/api";
import { EmptyState, ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { BarList, StatGrid, StatTile } from "@/components/stats";
import { formatINR, ROLE_LABELS } from "@/lib/format";
import type { ActiveErp, TeamPlan } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Period = "month" | "quarter" | "all";

interface NameAmount { name: string; amount: string }

export interface InsightsSummary {
  period: Period;
  role: string;
  requests: {
    open_by_status: Record<string, number>;
    open_total: number;
    waiting_by_step: { step: string; count: number; oldest_hours: string }[];
    approval_hours_average: string | null;
    approval_hours_median: string | null;
    approved_count: number;
    slowest_approvers: { approver: string; decisions: number; average_hours: string }[];
  };
  invoices: null | {
    total: number;
    by_status: Record<string, number>;
    on_hold_count: number;
    on_hold_amount_at_risk: string;
    rejected_total: string;
    first_pass_match_rate: string | null;
    matched_first_time: number;
    match_attempted: number;
    exceptions_by_code: { code: string; count: number }[];
    extraction: { read_by_ai: number; manual_entry: number; invoices_corrected: number; field_edits: number };
  };
  spend: null | {
    approved_requests_total: string;
    by_category: NameAmount[];
    by_cost_center: NameAmount[];
    approved_invoices_total: string;
    top_vendors: NameAmount[];
  };
  erp_drafts: null | { doc_type: string; state: string; count: number }[];
  sections: Record<string, unknown>;
}

const PERIODS: { id: Period; label: string }[] = [
  { id: "month", label: "This month" },
  { id: "quarter", label: "This quarter" },
  { id: "all", label: "All time" },
];

/** Exception codes in plain English (the same words the matching rules use, BUILD_PLAN §6). */
const EXCEPTION_LABELS: Record<string, string> = {
  PRICE_VARIANCE: "Price above the PO",
  QTY_EXCEEDS_RECEIPT: "More billed than received",
  TAX_TYPE_MISMATCH: "Wrong GST type",
  ARITHMETIC_MISMATCH: "Totals don't add up",
  VENDOR_MISMATCH: "Different vendor from the PO",
  DUPLICATE_BLOCKING: "Duplicate invoice",
  DUPLICATE_SUSPECTED: "Possible duplicate",
  LINE_UNPAIRED: "Line not on the PO",
  PO_NOT_OPEN: "PO closed or cancelled",
  PO_NOT_FOUND: "No PO found",
  GSTIN_INVALID: "Invalid GSTIN",
  GSTIN_CHECKSUM: "GSTIN check digit",
};

const STEP_LABEL = (role: string) => ROLE_LABELS[role] ?? role;

function hours(value: string | null): string {
  if (value === null) return "—";
  const h = Number(value);
  return h >= 48 ? `${(h / 24).toFixed(1)} days` : `${value} h`;
}

function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div role="group" aria-label="Period" className="flex rounded-lg border border-border bg-white p-0.5">
      {PERIODS.map((p) => (
        <button key={p.id} type="button" onClick={() => onChange(p.id)} aria-pressed={value === p.id}
                className={`rounded-md px-3 py-1.5 text-sm ${value === p.id ? "bg-navy text-white" : "text-heading hover:bg-ice"}`}>
          {p.label}
        </button>
      ))}
    </div>
  );
}

interface OverdueSection {
  sla_hours: number;
  count: number;
  rows: { request_id: string; number: string; title: string; waiting_on: string; age_hours: string; nudges: number }[];
}

interface BudgetSection {
  fiscal_year: string;
  quarter: number;
  rows: { cost_center: string; budget: string; committed: string; invoiced: string; pct_used: string | null; over: boolean }[];
}

/** Step 22 sections: approvals past the time limit, and this quarter's budgets (warnings only). */
function WorkflowSections({ sections }: { sections: Record<string, unknown> }) {
  const overdue = sections.overdue_approvals as OverdueSection | undefined;
  const budgets = sections.budgets as BudgetSection | undefined;
  if (!overdue && !budgets) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {overdue ? (
        <Panel title={`Overdue approvals (waiting over ${overdue.sla_hours} h) · ${overdue.count}`}
               actions={<Link href="/tasks" className="text-sm text-primary hover:underline">My tasks</Link>}>
          {overdue.rows.length ? (
            <ul className="flex flex-col gap-2 text-sm">
              {overdue.rows.map((r) => (
                <li key={r.request_id} className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link href={`/requests/${r.request_id}`} className="font-medium text-primary hover:underline">{r.number} · {r.title}</Link>
                  <span className="text-error">{hours(r.age_hours)} on {r.waiting_on}{r.nudges ? ` · nudged ${r.nudges}×` : ""}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-success">No approval is past the time limit.</p>}
        </Panel>
      ) : null}
      {budgets ? (
        <Panel title={`Budget used · ${budgets.fiscal_year} Q${budgets.quarter}`}
               actions={<Link href="/rules" className="text-sm text-primary hover:underline">Edit budgets</Link>}>
          <BarList rows={budgets.rows.map((b) => ({
            label: `${b.cost_center} · ${formatINR(b.committed)} of ${formatINR(b.budget)}${b.over ? " · over budget" : ""}`,
            value: b.pct_used ?? "0", display: b.pct_used ? `${b.pct_used}%` : "—",
          }))} empty="No budgets set for this quarter." color="bg-success" />
          <p className="mt-3 text-xs text-muted-foreground">Committed = requests in approval or approved. Budgets warn; they never block.</p>
        </Panel>
      ) : null}
    </div>
  );
}

interface PaymentsSection { due: string; in_runs: string; paid: string; failed: string; held_by_risk: string; tds_deducted: string }
interface GstSection { periods: string[]; itc_at_risk: string; missing_in_2b: number; amount_differs: number }
interface CloseSection { period: string; status: string; done: number; total: number }

/** Steps 25-27 sections: simulated payments, GSTR-2B credit at risk, and this month's close progress. */
function MoneySections({ sections }: { sections: Record<string, unknown> }) {
  const payments = sections.payments as PaymentsSection | undefined;
  const gst = sections.gst as GstSection | undefined;
  const close = sections.close as CloseSection | undefined;
  if (!payments && !gst && !close) return null;
  return (
    <StatGrid>
      {payments ? (
        <>
          <StatTile label="Approved, still to pay" value={formatINR(payments.due)} sub={<Link href="/payments" className="text-primary hover:underline">Payments</Link>} />
          <StatTile label="Held by payment-risk checks" value={formatINR(payments.held_by_risk)} tone={Number(payments.held_by_risk) ? "warn" : "good"} />
          <StatTile label="Paid (simulated)" value={formatINR(payments.paid)} sub={`TDS deducted ${formatINR(payments.tds_deducted)}`} />
        </>
      ) : null}
      {gst ? (
        <StatTile label="GST credit at risk (not in GSTR-2B)" value={formatINR(gst.itc_at_risk)} tone={Number(gst.itc_at_risk) ? "bad" : "good"}
                  sub={<Link href="/gst" className="text-primary hover:underline">{gst.missing_in_2b} missing · {gst.amount_differs} differ</Link>} />
      ) : null}
      {close ? (
        <StatTile label={`Month-end close · ${close.period}`} value={close.status === "closed" ? "Closed" : `${close.done} of ${close.total} checks`}
                  tone={close.status === "closed" || close.done === close.total ? "good" : "warn"}
                  sub={<Link href="/close" className="text-primary hover:underline">Open the close</Link>} />
      ) : null}
    </StatGrid>
  );
}

/** DualEntry-style "what changed": numbers computed by Orrfin, worded by AI (or a template). */
function WhatChanged({ role }: { role: string }) {
  const [period, setPeriod] = useState<"month" | "quarter">("month");
  const [notes, setNotes] = useState<{ bullets: string[]; source: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (role === "requester") return null;

  async function explain(p: "month" | "quarter") {
    setPeriod(p);
    setBusy(true);
    setError(null);
    try {
      setNotes(await post(`/insights/notes?period=${p}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not explain.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="What changed" actions={
      <div className="flex gap-2">
        <Button size="sm" variant={period === "month" && notes ? "default" : "outline"} disabled={busy} onClick={() => void explain("month")}>vs last month</Button>
        <Button size="sm" variant={period === "quarter" && notes ? "default" : "outline"} disabled={busy} onClick={() => void explain("quarter")}>vs last quarter</Button>
      </div>}>
      {notes ? (
        <>
          <ul className="list-disc pl-5 text-sm">{notes.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
          <p className="mt-2 text-xs text-muted-foreground">
            {notes.source.startsWith("template") ? "Written from Orrfin's numbers by a template." : `AI-written by ${notes.source} from Orrfin's numbers; every ₹ figure was checked.`}
          </p>
        </>
      ) : <p className="text-sm text-muted-foreground">{busy ? "Comparing…" : "Compare this period with the previous one, in plain words."}</p>}
      <ErrorNotice message={error} />
    </Panel>
  );
}

function ErpDrafts({ rows }: { rows: { doc_type: string; state: string; count: number }[] }) {
  const sum = (state: string) => rows.filter((r) => r.state === state).reduce((n, r) => n + r.count, 0);
  const failed = sum("FAILED") + sum("UNKNOWN");
  return (
    <StatTile label="Drafts written to the ERP" value={sum("CONFIRMED")}
              tone={failed ? "bad" : "default"}
              sub={failed ? `${failed} failed or unknown: check the ERP panel` : `${sum("PENDING") + sum("SENT")} in progress`} />
  );
}

const CHECKLIST_KEY = "orrfin.home.checklist.hidden";

/**
 * Step 41: an admin's first steps, each ticked from real data, never from clicks. Hidden once every
 * step is done, or when the admin closes it (remembered on this browser only).
 */
function GettingStarted({ hasRequests }: { hasRequests: boolean }) {
  const erp = useApi<ActiveErp>("/connectors/active").data;
  const plan = useApi<TeamPlan>("/team/plan").data;
  const entities = useApi<unknown[]>("/entities").data;
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHidden(window.localStorage.getItem(CHECKLIST_KEY) === "1");
    } catch {
      setHidden(false);
    }
  }, []);

  const steps = [
    { label: "Connect your ERP", detail: erp ? `${erp.name} is connected (${erp.mode}).` : "Pick the ERP Orrfin reads POs and vendors from.",
      href: "/connectors", done: Boolean(erp) },
    { label: "Invite your team", detail: "Requesters are free. Approvers, buyers and finance use a seat.",
      href: "/settings/team?invite=1", done: Boolean(plan && (plan.seats_used + plan.requesters > 1 || plan.pending_invites > 0)) },
    { label: "Add your legal entities", detail: "The companies you buy for, with their tax registration.",
      href: "/settings/entities", done: Boolean(entities && entities.length > 0) },
    { label: "Raise the first request", detail: "See approvals, the PO and the invoice check end to end.",
      href: "/requests/new", done: hasRequests },
  ];
  const done = steps.filter((s) => s.done).length;
  if (hidden || !plan || done === steps.length) return null;

  function close() {
    setHidden(true);
    try { window.localStorage.setItem(CHECKLIST_KEY, "1"); } catch { /* hidden for this visit only */ }
  }

  return (
    <section className="mb-6 rounded-xl border border-border bg-white shadow-raised" aria-label="Getting started">
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <h2 className="text-[15px] font-semibold text-heading">Set up your workspace</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{done} of {steps.length} done</p>
        </div>
        <div className="flex items-center gap-3">
          <span aria-hidden className="hidden h-2 w-32 overflow-hidden rounded-full bg-ice sm:block">
            <span className="block h-full rounded-full bg-brand-blue" style={{ width: `${(done / steps.length) * 100}%` }} />
          </span>
          <button type="button" onClick={close} aria-label="Hide setup steps" className="rounded-md p-1 text-muted-foreground hover:bg-ice hover:text-heading">
            <X className="size-4" aria-hidden />
          </button>
        </div>
      </div>
      <ol className="grid divide-y divide-border sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4">
        {steps.map((step, i) => (
          <li key={step.label} className="sm:border-r sm:border-border last:border-r-0">
            <Link href={step.href} className="group flex h-full gap-3 px-5 py-4 hover:bg-ice-light">
              <span className={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                step.done ? "bg-success text-white" : "border border-border bg-white text-heading"}`}>
                {step.done ? <Check className="size-3.5" aria-label="Done" /> : i + 1}
              </span>
              <span className="min-w-0">
                <span className={`flex items-center gap-1 text-sm font-medium ${step.done ? "text-muted-foreground line-through" : "text-heading"}`}>
                  {step.label}
                  {step.done ? null : <ChevronRight className="size-3.5 text-muted-foreground group-hover:text-heading" aria-hidden />}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{step.detail}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function HomePage() {
  const me = useMe();
  const [period, setPeriod] = useState<Period>("quarter");
  const { data, error, loading } = useApi<InsightsSummary>(`/insights/summary?period=${period}`);

  return (
    <>
      <PageHeader
        title={`Good day, ${me.full_name.split(" ")[0]}`}
        description={me.role === "requester" ? "Your requests at a glance." : "Where money is waiting, held or flowing."}
        actions={
          <>
            <PeriodPicker value={period} onChange={setPeriod} />
            <Link href="/requests/new" className={buttonVariants({ size: "lg" })}>
              <Plus aria-hidden /> New request
            </Link>
          </>
        }
      />
      <ErrorNotice message={error} />
      {me.role === "admin" && data ? (
        <GettingStarted hasRequests={data.requests.open_total + data.requests.approved_count > 0} />
      ) : null}
      {loading && !data ? <Loading /> : data ? <Dashboard data={data} /> : null}
    </>
  );
}

function Dashboard({ data }: { data: InsightsSummary }) {
  const { requests, invoices, spend, erp_drafts } = data;
  return (
    <div className="flex flex-col gap-6">
      <StatGrid>
        <StatTile label="Open requests" value={requests.open_total}
                  sub={`${requests.open_by_status.in_approval ?? 0} in approval · ${requests.open_by_status.with_buyer ?? 0} with a buyer`} />
        <StatTile label="Average approval time" value={hours(requests.approval_hours_average)}
                  sub={requests.approved_count ? `median ${hours(requests.approval_hours_median)} · ${requests.approved_count} approved` : "No approvals finished yet"} />
        {invoices ? (
          <>
            <StatTile label="Invoices on hold" value={invoices.on_hold_count} tone={invoices.on_hold_count ? "warn" : "good"}
                      sub={<><span className="font-medium text-error">{formatINR(invoices.on_hold_amount_at_risk)}</span> at risk, blocked</>} />
            <StatTile label="Matched first time" value={invoices.first_pass_match_rate ? `${invoices.first_pass_match_rate}%` : "—"}
                      sub={`${invoices.matched_first_time} of ${invoices.match_attempted} invoices`} />
          </>
        ) : null}
      </StatGrid>

      <WhatChanged role={data.role} />
      <WorkflowSections sections={data.sections} />
      <MoneySections sections={data.sections} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Where approvals are waiting">
          {requests.waiting_by_step.length ? (
            <BarList rows={requests.waiting_by_step.map((w) => ({
              label: `${STEP_LABEL(w.step)} (oldest ${hours(w.oldest_hours)})`, value: w.count, display: `${w.count}`,
            }))} empty="" color="bg-warning" />
          ) : <p className="text-sm text-muted-foreground">Nothing is waiting for approval.</p>}
        </Panel>
        <Panel title="Slowest approvers (average wait)">
          <BarList rows={requests.slowest_approvers.map((a) => ({
            label: `${a.approver} · ${a.decisions} decision${a.decisions === 1 ? "" : "s"}`, value: a.average_hours, display: hours(a.average_hours),
          }))} empty="No approvals decided in this period." color="bg-navy-soft" />
        </Panel>

        {invoices ? (
          <Panel title="Why invoices were held">
            <BarList rows={invoices.exceptions_by_code.map((e) => ({
              label: EXCEPTION_LABELS[e.code] ?? e.code, value: e.count, display: `${e.count}`,
            }))} empty="No invoices on hold." color="bg-error" />
          </Panel>
        ) : null}
        {spend ? (
          <Panel title={`Approved spend by category · ${formatINR(spend.approved_requests_total)}`}>
            <BarList rows={spend.by_category.map((c) => ({ label: c.name, value: c.amount, display: formatINR(c.amount) }))}
                     empty="No requests approved in this period." />
          </Panel>
        ) : null}
        {spend ? (
          <Panel title="Approved spend by cost centre">
            <BarList rows={spend.by_cost_center.map((c) => ({ label: c.name, value: c.amount, display: formatINR(c.amount) }))}
                     empty="No requests approved in this period." color="bg-cyan" />
          </Panel>
        ) : null}
        {spend ? (
          <Panel title={`Top vendors by approved invoices · ${formatINR(spend.approved_invoices_total)}`}>
            <BarList rows={spend.top_vendors.map((v) => ({ label: v.name, value: v.amount, display: formatINR(v.amount) }))}
                     empty="No invoices approved in this period." color="bg-blue-dark" />
          </Panel>
        ) : null}
      </div>

      {invoices && erp_drafts ? (
        <StatGrid>
          <ErpDrafts rows={erp_drafts} />
          <StatTile label="Invoices rejected (money stopped)" value={formatINR(invoices.rejected_total)} />
          <StatTile label="Invoices read by AI" value={invoices.extraction.read_by_ai}
                    sub={`${invoices.extraction.manual_entry} typed by hand after AI was unavailable`} />
          <StatTile label="Invoices a person corrected" value={invoices.extraction.invoices_corrected}
                    sub={`${invoices.extraction.field_edits} field edits, all audited`} />
        </StatGrid>
      ) : null}

      {!invoices && requests.open_total === 0 ? (
        <EmptyState>You have no open requests. <Link href="/requests/new" className="text-primary hover:underline">Start one</Link>.</EmptyState>
      ) : null}
    </div>
  );
}
