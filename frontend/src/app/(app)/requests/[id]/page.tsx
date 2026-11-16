"use client";

/**
 * Request page (PROMPTS Step 5): details, a status timeline (submitted → with buyer → step 1 → …
 * → approved), the actions this user may take right now, and the audit trail.
 * Which buttons appear comes from `allowed`, computed by the server with the same rules that
 * enforce the action (BUILD_PLAN §9), so the page never offers a click the server would refuse.
 *
 * Need-first workspaces (Step 42, ADR 0012) show the need's own journey instead: submitted → manager
 * approved → with procurement → on a PO → ordered, the WhatsApp or email message it came from, and which
 * purchase order each line is on.
 */
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Check,
  Mail,
  MessageCircle,
  Network,
  CircleCheck,
  CircleDot,
  CircleX,
  PackageCheck,
  Send,
  Undo2,
  UserPlus,
} from "lucide-react";

import { AsideCard, BackLink, Chain, DetailLayout, type ChainStep } from "@/components/detail";
import { ErpSyncPanel } from "@/components/erp-sync-panel";
import { BudgetNotice, RemindersPanel, stepName } from "@/components/workflow";
import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { RequestForm, toPayload } from "@/components/request-form";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { MetaList, PersonCell } from "@/components/ui/display";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { patch, post } from "@/lib/api";
import {
  formatDate,
  formatDateTime,
  formatINR,
  formatQty,
  lineTotal,
  requestNumber,
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
  // Step 42 (need-first)
  need_approved: "Manager approved the need: with procurement",
  placed_on_po: "Put on a purchase order",
  order_status_changed: "Updated from its purchase order",
};

const isNeedFirst = (request: RequestDetail) => request.intake_flow === "need_first";

// --- Status timeline -------------------------------------------------------------------------------

function NeedStages({ request }: { request: RequestDetail }) {
  const s = request.status;
  const stages: { label: string; state: "done" | "current" | "todo" | "stopped" }[] = [
    { label: "Submitted", state: s === "draft" ? "current" : "done" },
  ];
  const firstPending = request.current_steps.find((st) => st.decision === null)?.step;
  const steps = request.current_steps.length
    ? request.current_steps
    : [{ step: 1, required_role: "manager", decision: null } as RequestDetail["current_steps"][number]];
  for (const st of steps) {
    let state: "done" | "current" | "todo" | "stopped" = "todo";
    if (st.decision === "approve") state = "done";
    else if (st.decision === "reject" || st.decision === "return") state = "stopped";
    else if (s === "in_approval" && st.step === firstPending) state = "current";
    stages.push({ label: st.required_role === "manager" ? "Manager approves" : stepName(st), state });
  }
  stages.push({ label: "With procurement", state: s === "with_buyer" ? "current" : ["po_drafted", "po_open"].includes(s) ? "done" : "todo" });
  stages.push({ label: "On a PO", state: s === "po_drafted" ? "current" : s === "po_open" ? "done" : "todo" });
  stages.push({ label: "Ordered", state: s === "po_open" ? "done" : "todo" });
  return <StageList stages={stages} />;
}

function StageTimeline({ request }: { request: RequestDetail }) {
  if (isNeedFirst(request)) return <NeedStages request={request} />;
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
    stages.push({ label: `Step ${st.step}: ${stepName(st)}`, state });
  }
  stages.push({ label: "Approved", state: ["approved", "po_drafted", "po_open"].includes(s) ? "done" : "todo" });
  return <StageList stages={stages} />;
}

function StageList({ stages }: { stages: { label: string; state: "done" | "current" | "todo" | "stopped" }[] }) {
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

function chainSteps(request: RequestDetail): ChainStep[] {
  const firstOpen = request.current_steps.find((s) => s.decision === null)?.step;
  return request.current_steps.map((s) => ({
    key: s.step,
    label: `Step ${s.step}: ${stepName(s)}`,
    person: s.decision === null ? undefined
      : `${s.decision === "approve" ? "Approved" : s.decision === "reject" ? "Rejected" : "Returned"} by ${s.approver_name}`,
    note: s.decided_at ? formatDateTime(s.decided_at) : undefined,
    state: s.decision === "approve" ? "done" : s.decision ? "stopped"
      : s.step === firstOpen && request.status === "in_approval" ? "current" : "waiting",
  }));
}

function NeedLinesTable({ request }: { request: RequestDetail }) {
  const priced = Number(request.amount) > 0;
  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th className={table.th}>#</th>
            <th className={table.th}>What</th>
            <th className={`${table.th} ${table.num}`}>Qty</th>
            <th className={table.th}>Unit</th>
            {priced ? <th className={`${table.th} ${table.num}`}>Price if known</th> : null}
            <th className={table.th}>Purchase order</th>
          </tr>
        </thead>
        <tbody>
          {request.lines.map((l) => (
            <tr key={l.id}>
              <td className={table.td}>{l.line_no}</td>
              <td className={table.td}>{l.description}</td>
              <td className={`${table.td} ${table.num}`}>{formatQty(l.qty)}</td>
              <td className={table.td}>{l.unit ?? "—"}</td>
              {priced ? <td className={`${table.td} ${table.num}`}>{Number(l.est_rate) > 0 ? formatINR(l.est_rate) : "—"}</td> : null}
              <td className={table.td}>
                {l.placement ? (
                  <Link href={`/orders/${l.placement.po_id}`} className="text-primary hover:underline">
                    {l.placement.po_number}{l.placement.po_status === "sent" ? " · sent" : ""}
                  </Link>
                ) : <span className="text-muted-foreground">Not ordered yet</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceMessage({ request }: { request: RequestDetail }) {
  if (!request.source_message) return null;
  const whatsapp = request.source_channel === "whatsapp";
  const Icon = whatsapp ? MessageCircle : Mail;
  return (
    <Panel title={whatsapp ? "Came in on WhatsApp" : "Came in by email"}>
      <p className="whitespace-pre-wrap rounded-lg bg-ice-light px-3 py-2 text-sm text-heading">
        <Icon className="mr-1.5 inline size-4 text-muted-foreground" aria-hidden />{request.source_message}
      </p>
      {request.entered_by_name ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Entered by {request.entered_by_name} for {request.requester_name}, who checked and submitted it.
        </p>
      ) : null}
    </Panel>
  );
}

function LinesTable({ request }: { request: RequestDetail }) {
  if (isNeedFirst(request)) return <NeedLinesTable request={request} />;
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
    <Panel title={`Your decision: step ${step} (${stepInfo ? stepName(stepInfo) : ""})`}>
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
            <CircleCheck aria-hidden /> {Number(request.amount) > 0 ? `Approve ${formatINR(request.amount)}` : "Approve the need"}
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
  const { data: request, setData, error, loading, reload } = useApi<RequestDetail>(`/requests/${id}`);
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

  const needFirst = isNeedFirst(request);
  const channelLabel = { form: "Orrfin form", whatsapp: "WhatsApp message", email: "Email" }[request.source_channel ?? "form"];
  const details = (
    <AsideCard title="Details" actions={request.allowed.edit && !editing
      ? <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button> : undefined}>
      <MetaList rows={needFirst ? [
        { label: "Rough total", value: Number(request.amount) > 0 ? formatINR(request.amount) : "Priced by procurement" },
        { label: "Needed by", value: formatDate(request.needed_by) },
        { label: "Kind of thing", value: request.category_name },
        { label: "Cost centre", value: request.cost_center || "—" },
        { label: "Came in by", value: channelLabel },
        { label: "Waiting on", value: request.waiting_on ?? "—" },
      ] : [
        { label: "Amount", value: <span className="text-base font-semibold text-heading">{formatINR(request.amount)}</span> },
        { label: "Needed by", value: formatDate(request.needed_by) },
        { label: "Category", value: request.category_name },
        { label: "Cost centre", value: request.cost_center || "—" },
        { label: "Vendor", value: request.vendor_name ?? (request.suggested_vendor_name ? `${request.suggested_vendor_name} (suggested)` : "—") },
        { label: "Waiting on", value: request.waiting_on ?? "—" },
      ]} />
      <div className="mt-3 space-y-2.5 border-t border-border pt-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-muted-foreground">Requested by</span>
          <PersonCell name={request.requester_name} size="xs" />
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="text-muted-foreground">{needFirst ? "Procurement" : "Buyer"}</span>
          {request.buyer_name ? <PersonCell name={request.buyer_name} size="xs" /> : <span className="text-muted-foreground">Not assigned</span>}
        </div>
      </div>
      {request.allowed.submit ? (
        <Button className="mt-4 w-full" onClick={submit}><Send aria-hidden /> {needFirst ? "Send to my manager" : "Submit for approval"}</Button>
      ) : null}
    </AsideCard>
  );

  return (
    <>
      <PageHeader
        meta={<BackLink href="/requests" label="Requests" />}
        title={`${requestNumber(request.number)} · ${request.title}`}
        description={`${request.category_name} · requested by ${request.requester_name}`}
        actions={
          <div className="flex items-center gap-3">
            <StatusBadge status={request.status} />
            <Link href={`/control-graph?request_id=${request.id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
              <Network className="size-4" aria-hidden /> Control Graph
            </Link>
          </div>
        }
      />
      <div className="mb-6 rounded-xl border border-border bg-white px-4 py-3 shadow-raised">
        <StageTimeline request={request} />
      </div>
      <DetailLayout
        aside={
          <>
            {details}
            {request.current_steps.length > 0 ? (
              <AsideCard title={`Approval chain${request.approval_round > 1 ? ` · round ${request.approval_round}` : ""}`}>
                <Chain steps={chainSteps(request)} />
              </AsideCard>
            ) : null}
          </>
        }
        main={
          <>
            {request.ready_for_po ? (
              <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
                <PackageCheck className="size-4" aria-hidden />
                Approved and ready for PO. Orrfin drafts the purchase order in the active ERP; a person submits it there.
              </p>
            ) : null}
            <ErpSyncPanel sync={request.po_sync} note={request.po_sync_note} what="PO" onChange={() => void reload()} />
            {request.status === "returned" ? (
              <p className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
                Returned: {request.current_steps.find((s) => s.decision === "return")?.reason ?? "see the audit trail"}
              </p>
            ) : null}
            <ErrorNotice message={actionError} />
            {request.status === "with_buyer" && needFirst ? (
              <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
                <PackageCheck className="size-4" aria-hidden />
                Approved by the manager. Procurement now chooses the vendor and price and puts it on a purchase order.
              </p>
            ) : null}
            {request.status === "po_open" && needFirst ? (
              <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
                <PackageCheck className="size-4" aria-hidden /> Ordered: the purchase order has been sent to the vendor.
              </p>
            ) : null}
            <SourceMessage request={request} />

            {request.allowed.decide_step ? <DecisionPanel request={request} onChange={setData} /> : null}
            {request.allowed.assign_buyer ? <AssignPanel request={request} onChange={setData} /> : null}
            {request.allowed.buyer_edit ? <BuyerPanel key={request.updated_at} request={request} onChange={setData} /> : null}

            {editing ? (
              <RequestForm
                initial={request}
                needFirst={needFirst}
                submitLabel="Save changes"
                onSave={async (values) => {
                  setData(await patch<RequestDetail>(`/requests/${request.id}`, toPayload(values)));
                  setEditing(false);
                }}
              />
            ) : (
              <>
                {request.justification ? (
                  <Panel title="Why it's needed"><p className="text-sm leading-relaxed text-foreground">{request.justification}</p></Panel>
                ) : null}
                <LinesTable request={request} />
              </>
            )}

            {request.status === "in_approval" ? <RemindersPanel requestId={request.id} version={request.updated_at} /> : null}
            {["with_buyer", "in_approval"].includes(request.status) && request.cost_center ? (
              <BudgetNotice query={`request_id=${request.id}&v=${encodeURIComponent(request.updated_at)}`} />
            ) : null}

            {request.timeline.length ? <AuditTrail request={request} /> : <EmptyState>No events yet.</EmptyState>}
          </>
        }
      />
    </>
  );
}
