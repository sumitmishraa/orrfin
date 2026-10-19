"use client";

/**
 * Home: the control dashboard (BUILD_PLAN v2.3 change 23; PROMPTS Step 21).
 * Every number comes from GET /insights/summary, computed by rules on the server, never by AI.
 * Requesters see their own requests only; everyone else also sees invoices, spend and ERP drafts.
 */
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { useMe } from "@/components/session";
import { buttonVariants } from "@/components/ui/button";
import { EmptyState, ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { BarList, StatGrid, StatTile } from "@/components/stats";
import { formatINR, ROLE_LABELS } from "@/lib/format";
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
export const EXCEPTION_LABELS: Record<string, string> = {
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

function ErpDrafts({ rows }: { rows: { doc_type: string; state: string; count: number }[] }) {
  const sum = (state: string) => rows.filter((r) => r.state === state).reduce((n, r) => n + r.count, 0);
  const failed = sum("FAILED") + sum("UNKNOWN");
  return (
    <StatTile label="Drafts written to the ERP" value={sum("CONFIRMED")}
              tone={failed ? "bad" : "default"}
              sub={failed ? `${failed} failed or unknown: check the ERP panel` : `${sum("PENDING") + sum("SENT")} in progress`} />
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
