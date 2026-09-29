"use client";

/**
 * Request page (PROMPTS Step 5): details, a status timeline (submitted → with buyer → step 1 → …
 * → approved), the actions this user may take right now, and the audit trail.
 * Which buttons appear comes from `allowed`, computed by the server with the same rules that
 * enforce the action (BUILD_PLAN §9), so the page never offers a click the server would refuse.
 */
import { useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import {
  Check,
  CircleCheck,
  CircleDot,
  CircleX,
  PackageCheck,
  Send,
  Undo2,
  UserPlus,
} from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { RequestForm } from "@/components/request-form";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { patch, post } from "@/lib/api";
import {
  formatDate,
  formatDateTime,
  formatINR,
  formatQty,
  lineTotal,
  requestNumber,
  ROLE_LABELS,
  sumMoney,
} from "@/lib/format";
import type { RequestDetail, UserRef, Vendor } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const ACTION_LABELS: Record<string, string> = {
  created: "Request created",
  edited: "Request edited",
  submitted: "Submitted",
  buyer_assigned: "Buyer assigned by admin",
  buyer_updated: "Buyer set vendor, item codes and rates",
  sent_for_approval: "Sent for approval",
  approval_chain_restarted: "Amount changed: approval chain restarted",
  step_approved: "Step approved",
  approved: "Final approval: ready for PO",
  rejected: "Rejected",
  returned: "Returned to requester",
};

// --- Status timeline -------------------------------------------------------------------------------

function StageTimeline({ request }: { request: RequestDetail }) {
  const s = request.status;
  const submittedDone = !["draft"].includes(s);
  const buyerDone = ["in_approval", "approved", "rejected", "po_drafted", "po_open"].includes(s);
  const stages: { label: string; state: "done" | "current" | "todo" | "stopped" }[] = [
    { label: "Submitted", state: submittedDone ? "done" : "current" },
    { label: "With buyer", state: buyerDone ? "done" : ["with_buyer", "submitted"].includes(s) ? "current" : "todo" },
  ];
  const steps = request.current_steps.length
    ? request.current_steps
    : [{ step: 1, required_role: "manager", decision: null } as RequestDetail["current_steps"][number]];
  const firstPending = steps.find((st) => st.decision === null)?.step;
  for (const st of steps) {
    let state: "done" | "current" | "todo" | "stopped" = "todo";
    if (st.decision === "approve") state = "done";
    else if (st.decision === "reject" || st.decision === "return") state = "stopped";
    else if (s === "in_approval" && st.step === firstPending) state = "current";
    stages.push({ label: `Step ${st.step}: ${ROLE_LABELS[st.required_role] ?? st.required_role}`, state });
  }
  stages.push({ label: "Approved", state: ["approved", "po_drafted", "po_open"].includes(s) ? "done" : "todo" });

  return (
    <ol aria-label="Progress" className="flex flex-wrap items-center gap-2">
      {stages.map((stage, i) => (
        <li key={stage.label} className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
              stage.state === "done"
                ? "border-success/30 bg-success/10 text-success"
                : stage.state === "current"
                  ? "border-warning/40 bg-warning/10 text-warning"
                  : stage.state === "stopped"
                    ? "border-error/30 bg-error/10 text-error"
                    : "border-border bg-white text-muted-foreground"
            }`}
          >
            {stage.state === "done" ? <Check className="size-3.5" aria-hidden /> : null}
            {stage.state === "current" ? <CircleDot className="size-3.5" aria-hidden /> : null}
            {stage.state === "stopped" ? <CircleX className="size-3.5" aria-hidden /> : null}
            {stage.label}
            <span className="sr-only">
              {stage.state === "done" ? "(done)" : stage.state === "current" ? "(current)" : stage.state === "stopped" ? "(stopped)" : "(not yet)"}
            </span>
          </span>
          {i < stages.length - 1 ? <span aria-hidden className="h-px w-4 bg-border" /> : null}
        </li>
      ))}
    </ol>
  );
}

// --- Panels ------------------------------------------------------------------------------------------

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

function LinesTable({ request }: { request: RequestDetail }) {
  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th className={table.th}>#</th>
            <th className={table.th}>Description</th>
            <th className={table.th}>Item code</th>
            <th className={`${table.th} ${table.num}`}>Qty</th>
            <th className={`${table.th} ${table.num}`}>Est. rate</th>
            <th className={`${table.th} ${table.num}`}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {request.lines.map((l) => (
            <tr key={l.id}>
              <td className={table.td}>{l.line_no}</td>
              <td className={table.td}>{l.description}</td>
              <td className={`${table.td} font-mono text-xs`}>{l.item_code ?? "—"}</td>
              <td className={`${table.td} ${table.num}`}>{formatQty(l.qty)}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(l.est_rate)}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(l.amount)}</td>
            </tr>
          ))}
          <tr>
            <td className={`${table.td} font-semibold text-heading`} colSpan={5}>Total</td>
            <td className={`${table.td} ${table.num} font-semibold text-heading`}>{formatINR(request.amount)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function BuyerPanel({ request, onChange }: { request: RequestDetail; onChange: (r: RequestDetail) => void }) {
  const vendors = useApi<Vendor[]>("/vendors");
  const [vendorId, setVendorId] = useState(request.vendor_id ?? request.suggested_vendor_id ?? "");
  const [lines, setLines] = useState(
    request.lines.map((l) => ({ id: l.id, description: l.description, item_code: l.item_code ?? "", qty: l.qty, est_rate: l.est_rate })),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const newTotal = sumMoney(lines.map((l) => lineTotal(formatQty(l.qty), l.est_rate)));
  const amountChanges = request.status === "in_approval" && newTotal !== request.amount;

  async function act(fn: () => Promise<RequestDetail>) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    patch<RequestDetail>(`/requests/${request.id}/buyer`, {
      vendor_id: vendorId || null,
      lines: lines.map(({ id, item_code, qty, est_rate }) => ({ id, item_code, qty, est_rate })),
    });

  return (
    <Panel title="Buyer: complete the request">
      <div className="flex flex-col gap-4">
        <Field label="Vendor (from ERP)" htmlFor="buyer-vendor"
               hint={vendors.data?.length === 0 ? "No vendors yet: run “Sync from ERP” on the POs page." : undefined}>
          <Select id="buyer-vendor" value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">Choose a vendor…</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>{v.name} · {v.gstin}</option>
            ))}
          </Select>
        </Field>
        {lines.map((line, i) => (
          <div key={line.id} className="grid items-end gap-3 md:grid-cols-[1fr_10rem_6rem_9rem]">
            <p className="pb-2 text-sm">{i + 1}. {line.description}</p>
            <Field label="Item code" htmlFor={`code-${i}`}>
              <Input id={`code-${i}`} value={line.item_code}
                     onChange={(e) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, item_code: e.target.value } : l)))} />
            </Field>
            <Field label="Qty" htmlFor={`bqty-${i}`}>
              <Input id={`bqty-${i}`} inputMode="decimal" value={formatQty(line.qty)}
                     onChange={(e) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, qty: e.target.value } : l)))} />
            </Field>
            <Field label="Rate (₹)" htmlFor={`brate-${i}`}>
              <Input id={`brate-${i}`} inputMode="decimal" value={line.est_rate}
                     onChange={(e) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, est_rate: e.target.value } : l)))} />
            </Field>
          </div>
        ))}
        <p className="text-sm">New total <span className="font-semibold tabular-nums">{formatINR(newTotal)}</span></p>
        {amountChanges ? (
          <p className="text-sm text-warning">Saving a different amount restarts the approval chain from step 1.</p>
        ) : null}
        <ErrorNotice message={error} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={() => act(save)}>Save changes</Button>
          {request.allowed.send_for_approval ? (
            <Button disabled={busy} onClick={() => act(async () => {
              await save();
              return post<RequestDetail>(`/requests/${request.id}/send-for-approval`);
            })}>
              <Send aria-hidden /> Save and send for approval
            </Button>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

function DecisionPanel({ request, onChange }: { request: RequestDetail; onChange: (r: RequestDetail) => void }) {
  const step = request.allowed.decide_step!;
  const stepInfo = request.current_steps.find((s) => s.step === step);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decide(decision: "approve" | "reject" | "return") {
    setBusy(true);
    setError(null);
    try {
      onChange(await post<RequestDetail>(`/requests/${request.id}/approvals/${step}/decision`, { decision, reason: reason || null }));
      setReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`Your decision: step ${step} (${ROLE_LABELS[stepInfo?.required_role ?? ""] ?? stepInfo?.required_role})`}>
      <div className="flex flex-col gap-3">
        <Field label="Reason (required to reject or return)" htmlFor="reason">
          <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
        </Field>
        {!request.allowed.can_approve && request.allowed.approve_blocked_reason ? (
          <p className="text-sm text-warning">You can’t approve: {request.allowed.approve_blocked_reason}</p>
        ) : null}
        <ErrorNotice message={error} />
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy || !request.allowed.can_approve} onClick={() => decide("approve")}>
            <CircleCheck aria-hidden /> Approve {formatINR(request.amount)}
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => decide("return")}>
            <Undo2 aria-hidden /> Return to requester
          </Button>
          <Button variant="destructive" disabled={busy} onClick={() => decide("reject")}>
            <CircleX aria-hidden /> Reject
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function AssignPanel({ request, onChange }: { request: RequestDetail; onChange: (r: RequestDetail) => void }) {
  const buyers = useApi<UserRef[]>("/users?role=buyer");
  const [buyerId, setBuyerId] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Panel title="Admin queue: this category has no buyer">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Assign to buyer" htmlFor="assign-buyer" className="min-w-64">
          <Select id="assign-buyer" value={buyerId} onChange={(e) => setBuyerId(e.target.value)}>
            <option value="">Choose…</option>
            {buyers.data?.map((b) => <option key={b.id} value={b.id}>{b.full_name}</option>)}
          </Select>
        </Field>
        <Button disabled={!buyerId} onClick={async () => {
          try {
            onChange(await post<RequestDetail>(`/requests/${request.id}/assign`, { buyer_id: buyerId }));
          } catch (e) {
            setError(e instanceof Error ? e.message : "Could not assign.");
          }
        }}>
          <UserPlus aria-hidden /> Assign
        </Button>
      </div>
      <div className="mt-3"><ErrorNotice message={error} /></div>
    </Panel>
  );
}

function AuditTrail({ request }: { request: RequestDetail }) {
  return (
    <Panel title="Audit trail">
      <ol className="flex flex-col gap-3">
        {request.timeline.map((e) => (
          <li key={e.seq} className="flex gap-3 text-sm">
            <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand-bright" aria-hidden />
            <div>
              <p className="font-medium text-heading">{ACTION_LABELS[e.action] ?? e.action}</p>
              <p className="text-xs text-muted-foreground">
                {e.actor_name ?? "System"} · {formatDateTime(e.at)}
                {typeof e.payload.step === "number" ? ` · step ${e.payload.step}` : ""}
              </p>
              {typeof e.payload.reason === "string" && e.payload.reason ? (
                <p className="mt-1 rounded-md bg-ice-light px-2 py-1 text-xs">“{e.payload.reason}”</p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

// --- Page --------------------------------------------------------------------------------------------

export default function RequestPage() {
  const { id } = useParams<{ id: string }>();
  const { data: request, setData, error, loading } = useApi<RequestDetail>(`/requests/${id}`);
  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error || !request) return <ErrorNotice message={error ?? "Request not found."} />;

  const submit = async () => {
    try {
      setData(await post<RequestDetail>(`/requests/${request.id}/submit`));
      setActionError(null);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not submit.");
    }
  };

  return (
    <>
      <PageHeader
        title={`${requestNumber(request.number)} · ${request.title}`}
        description={`${request.category_name} · requested by ${request.requester_name}`}
        actions={<StatusBadge status={request.status} />}
      />
      <div className="flex flex-col gap-6">
        <StageTimeline request={request} />

        {request.ready_for_po ? (
          <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
            <PackageCheck className="size-4" aria-hidden />
            Approved and ready for PO. Orrfin drafts the purchase order in ERPNext in a later step.
          </p>
        ) : null}
        {request.status === "returned" ? (
          <p className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
            Returned: {request.current_steps.find((s) => s.decision === "return")?.reason ?? "see the audit trail"}
          </p>
        ) : null}
        <ErrorNotice message={actionError} />

        {editing ? (
          <RequestForm
            initial={request}
            submitLabel="Save changes"
            onSave={async (values) => {
              setData(await patch<RequestDetail>(`/requests/${request.id}`, values));
              setEditing(false);
            }}
          />
        ) : (
          <>
            <Panel
              title="Details"
              actions={
                request.allowed.edit || request.allowed.submit ? (
                  <div className="flex gap-2">
                    {request.allowed.edit ? <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button> : null}
                    {request.allowed.submit ? <Button size="sm" onClick={submit}><Send aria-hidden /> Submit</Button> : null}
                  </div>
                ) : null
              }
            >
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Detail label="Amount"><span className="text-base font-semibold text-heading">{formatINR(request.amount)}</span></Detail>
                <Detail label="Needed by">{formatDate(request.needed_by)}</Detail>
                <Detail label="Cost centre">{request.cost_center || "—"}</Detail>
                <Detail label="Buyer">{request.buyer_name ?? "Not assigned"}</Detail>
                <Detail label="Vendor">{request.vendor_name ?? (request.suggested_vendor_name ? `${request.suggested_vendor_name} (suggested)` : "—")}</Detail>
                <Detail label="Waiting on">{request.waiting_on ?? "—"}</Detail>
                <Detail label="Justification">{request.justification || "—"}</Detail>
              </dl>
            </Panel>
            <LinesTable request={request} />
          </>
        )}

        {request.allowed.assign_buyer ? <AssignPanel request={request} onChange={setData} /> : null}
        {request.allowed.buyer_edit ? <BuyerPanel key={request.updated_at} request={request} onChange={setData} /> : null}
        {request.allowed.decide_step ? <DecisionPanel request={request} onChange={setData} /> : null}

        {request.current_steps.length > 0 ? (
          <Panel title={`Approval chain${request.approval_round > 1 ? ` (round ${request.approval_round})` : ""}`}>
            <ol className="flex flex-col gap-2">
              {request.current_steps.map((s) => (
                <li key={s.step} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-heading">Step {s.step}: {ROLE_LABELS[s.required_role] ?? s.required_role}</span>
                  <span className="text-muted-foreground">
                    {s.decision === null ? "· waiting" : `· ${s.decision === "approve" ? "approved" : s.decision === "reject" ? "rejected" : "returned"} by ${s.approver_name} on ${formatDateTime(s.decided_at!)}`}
                  </span>
                </li>
              ))}
            </ol>
          </Panel>
        ) : null}

        {request.timeline.length ? <AuditTrail request={request} /> : <EmptyState>No events yet.</EmptyState>}
      </div>
    </>
  );
}
