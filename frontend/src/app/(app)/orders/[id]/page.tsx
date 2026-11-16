"use client";

/**
 * One Orrfin purchase order (Step 42, ADR 0012): what is ordered and for whom, the approval chain,
 * the ERP draft, and "Send to vendor" with the exact email and WhatsApp text. Sending is simulated:
 * Orrfin records the message and shows it here; nothing leaves the building.
 * Buttons come from `allowed`, computed by the server with the rules that enforce each action (§9).
 */
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Ban, CircleCheck, CircleX, Download, Mail, Send, Undo2 } from "lucide-react";

import { AsideCard, BackLink, Chain, DetailLayout, type ChainStep } from "@/components/detail";
import { ErpSyncPanel } from "@/components/erp-sync-panel";
import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { WhatsAppPreview } from "@/components/workflow";
import { Button } from "@/components/ui/button";
import { MetaList } from "@/components/ui/display";
import { Field, Input, Textarea } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { API_URL, post } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, formatQty, requestNumber } from "@/lib/format";
import type { OrderPoDetail, VendorMessagePreview } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { OrderStatus, poNumber } from "../order-status";

const ROLE_WORDS: Record<string, string> = { finance: "Finance", admin: "Admin", approver: "Approver" };

function chainSteps(po: OrderPoDetail): ChainStep[] {
  const firstOpen = po.steps.find((s) => s.decision === null)?.step;
  return po.steps.map((s) => ({
    key: s.step,
    label: `Step ${s.step}: ${ROLE_WORDS[s.required_role] ?? s.required_role}`,
    person: s.decision === null ? undefined
      : `${s.decision === "approve" ? "Approved" : s.decision === "reject" ? "Rejected" : "Returned"} by ${s.approver_name}`,
    note: s.decided_at ? formatDateTime(s.decided_at) : s.reason ?? undefined,
    state: s.decision === "approve" ? "done" : s.decision ? "stopped"
      : s.step === firstOpen && po.status === "in_approval" ? "current" : "waiting",
  }));
}

function Lines({ po }: { po: OrderPoDetail }) {
  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th className={table.th}>#</th>
            <th className={table.th}>Item</th>
            <th className={table.th}>For</th>
            <th className={`${table.th} ${table.num}`}>Qty</th>
            <th className={`${table.th} ${table.num}`}>Rate</th>
            <th className={`${table.th} ${table.num}`}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {po.lines.map((l) => (
            <tr key={l.id}>
              <td className={table.td}>{l.line_no}</td>
              <td className={table.td}>
                <p className="font-medium text-heading">{l.description}</p>
                <p className="font-mono text-xs text-muted-foreground">{l.item_code}</p>
              </td>
              <td className={table.td}>
                <ul className="space-y-0.5 text-xs">
                  {l.sources.map((s) => (
                    <li key={s.request_id}>
                      <Link href={`/requests/${s.request_id}`} className="text-primary hover:underline">{requestNumber(s.request_number)}</Link>
                      {" "}{s.requester_name} · {formatQty(s.qty)}
                    </li>
                  ))}
                </ul>
              </td>
              <td className={`${table.td} ${table.num}`}>{formatQty(l.qty)} {l.unit ?? ""}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(l.rate)}</td>
              <td className={`${table.td} ${table.num}`}>{formatINR(l.amount)}</td>
            </tr>
          ))}
          <tr>
            <td className={`${table.td} font-semibold text-heading`} colSpan={5}>Total before GST</td>
            <td className={`${table.td} ${table.num} font-semibold text-heading`}>{formatINR(po.amount)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function DraftActions({ po, onChange }: { po: OrderPoDetail; onChange: (po: OrderPoDetail) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chain = po.chain_preview ?? [];
  async function act(path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    try {
      onChange(await post<OrderPoDetail>(`/ordering/pos/${po.id}/${path}`, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title={po.status === "returned" ? "Returned to you: fix it and submit again" : "Ready to submit"}>
      <p className="text-sm text-foreground">
        {chain.length
          ? <>At {formatINR(po.amount)} this needs approval from <b>{chain.map((r) => ROLE_WORDS[r] ?? r).join(" → ")}</b> before it can go to the vendor.</>
          : <>At {formatINR(po.amount)} this is within procurement&apos;s limit: it is approved as soon as you submit.</>}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {po.allowed.submit ? (
          <Button disabled={busy} onClick={() => void act("submit")}><Send aria-hidden /> Submit</Button>
        ) : null}
        {po.allowed.cancel ? (
          <Button variant="outline" disabled={busy} onClick={() => void act("cancel", { reason: null })}>
            <Ban aria-hidden /> Cancel PO (frees the needs)
          </Button>
        ) : null}
      </div>
      <ErrorNotice message={error} />
    </Panel>
  );
}

function DecisionPanel({ po, onChange }: { po: OrderPoDetail; onChange: (po: OrderPoDetail) => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const step = po.allowed.decide_step!;
  async function decide(decision: "approve" | "reject" | "return") {
    setBusy(true);
    setError(null);
    try {
      onChange(await post<OrderPoDetail>(`/ordering/pos/${po.id}/approvals/${step}/decision`, { decision, reason: reason || null }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the decision.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title={`Your decision: step ${step}`}>
      <Field label="Reason (needed to reject or return)" htmlFor="po-reason">
        <Textarea id="po-reason" rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {po.allowed.approve_blocked_reason ? <p className="mt-2 text-sm text-warning">{po.allowed.approve_blocked_reason}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled={busy || !po.allowed.can_approve} onClick={() => void decide("approve")}>
          <CircleCheck aria-hidden /> Approve {formatINR(po.amount)}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide("return")}><Undo2 aria-hidden /> Return to procurement</Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide("reject")}><CircleX aria-hidden /> Reject</Button>
      </div>
      <ErrorNotice message={error} />
    </Panel>
  );
}

function SendDialog({ po, open, onOpenChange, onSent }: {
  po: OrderPoDetail; open: boolean; onOpenChange: (open: boolean) => void; onSent: (po: OrderPoDetail) => void;
}) {
  const preview = useApi<VendorMessagePreview>(open ? `/ordering/pos/${po.id}/vendor-message` : null);
  const [to, setTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const address = to ?? preview.data?.to ?? "";
  async function send() {
    setBusy(true);
    setError(null);
    try {
      onSent(await post<OrderPoDetail>(`/ordering/pos/${po.id}/send`, { to: address }));
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg" title={`Send ${poNumber(po.number)} to ${po.vendor_name}`}
            description="Simulated: Orrfin records this email and shows it on the PO. No real email or WhatsApp message is sent."
            footer={
              <div className="flex w-full flex-wrap items-center justify-between gap-2">
                {preview.data ? <WhatsAppPreview text={preview.data.whatsapp} /> : <span />}
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                  <Button disabled={busy || !preview.data} onClick={() => void send()}><Send aria-hidden /> {busy ? "Sending…" : "Send email"}</Button>
                </div>
              </div>
            }>
      {!preview.data ? <Loading /> : (
        <div className="flex flex-col gap-3">
          <Field label="To" htmlFor="send-to" hint={preview.data.to ? "From the supplier's onboarding record." : "Type the vendor's email address."}>
            <Input id="send-to" type="email" value={address} onChange={(e) => setTo(e.target.value)} placeholder="orders@vendor.example" />
          </Field>
          <MetaList rows={[
            { label: "Subject", value: preview.data.subject },
            { label: "Attachment", value: <a className="text-primary hover:underline" href={`${API_URL}/documents/order-po/${po.id}`}>{preview.data.attachment_name}</a> },
          ]} />
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-ice-light p-3 font-sans text-sm text-heading">{preview.data.body}</pre>
          <ErrorNotice message={error} />
        </div>
      )}
    </Dialog>
  );
}

export default function OrderPage() {
  const { id } = useParams<{ id: string }>();
  const { data: po, setData, error, loading, reload } = useApi<OrderPoDetail>(`/ordering/pos/${id}`);
  const [sending, setSending] = useState(false);

  if (loading) return <Loading />;
  if (error || !po) return <ErrorNotice message={error ?? "Purchase order not found."} />;

  const erp = po.erp_sync?.erp_doc_name;
  return (
    <>
      <PageHeader
        meta={<BackLink href="/orders" label="Orders" />}
        title={`${poNumber(po.number)}${erp ? ` / ${erp}` : ""} · ${po.vendor_name}`}
        description={po.reference}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <OrderStatus status={po.status} />
            <a href={`${API_URL}/documents/order-po/${po.id}`}
               className="inline-flex items-center gap-1 rounded-lg border border-border bg-white px-3 py-1.5 text-sm text-heading hover:bg-ice">
              <Download className="size-4" aria-hidden /> PDF
            </a>
            {po.allowed.send ? (
              <Button onClick={() => setSending(true)}><Mail aria-hidden /> Send to vendor</Button>
            ) : null}
          </div>
        }
      />
      <DetailLayout
        aside={
          <>
            <AsideCard title="Details">
              <MetaList rows={[
                { label: "Total before GST", value: <span className="text-base font-semibold text-heading">{formatINR(po.amount)}</span> },
                { label: "Vendor", value: `${po.vendor_name}${po.vendor_gstin ? ` · ${po.vendor_gstin}` : ""}` },
                { label: "Deliver by", value: formatDate(po.needed_by) },
                { label: "Built by", value: po.created_by_name ?? "—" },
                { label: "ERP number", value: erp ?? "Not yet" },
                { label: "Sent", value: po.sent_at ? `${formatDateTime(po.sent_at)} by ${po.sent_by_name}` : "Not yet" },
              ]} />
            </AsideCard>
            {po.steps.length ? (
              <AsideCard title={`Approval${po.approval_round > 1 ? ` · round ${po.approval_round}` : ""}`}>
                <Chain steps={chainSteps(po)} />
              </AsideCard>
            ) : null}
          </>
        }
        main={
          <>
            {po.status === "approved" && !po.allowed.send && po.send_blocked_reason ? (
              <p role="status" className="rounded-xl border border-border bg-ice px-4 py-3 text-sm text-heading">{po.send_blocked_reason}</p>
            ) : null}
            {po.send_notes.map((n) => <p key={n} className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">{n}</p>)}
            {po.status === "sent" ? (
              <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm font-medium text-success">
                <Send className="size-4" aria-hidden /> Sent to {po.vendor_name}. The employees who asked can see their needs as ordered.
              </p>
            ) : null}
            {po.allowed.submit || po.allowed.cancel ? <DraftActions po={po} onChange={setData} /> : null}
            {po.allowed.decide_step ? <DecisionPanel po={po} onChange={setData} /> : null}
            <ErpSyncPanel sync={po.erp_sync} what="PO" onChange={() => void reload()} />
            <Lines po={po} />
            {po.note_to_vendor ? <Panel title="Note to the vendor"><p className="text-sm">{po.note_to_vendor}</p></Panel> : null}
            <Panel title="Messages to the vendor">
              {po.messages.length ? (
                <ul className="space-y-3">
                  {po.messages.map((m) => (
                    <li key={m.id} className="rounded-lg border border-border p-3 text-sm">
                      <p className="font-medium text-heading">{m.subject}</p>
                      <p className="text-xs text-muted-foreground">
                        {m.channel === "email" ? "Email" : "WhatsApp"} to {m.to} · {formatDateTime(m.at)} · by {m.by} · simulated
                        {m.attachment_name ? ` · attached ${m.attachment_name}` : ""}
                      </p>
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-primary">Show the email</summary>
                        <pre className="mt-2 whitespace-pre-wrap font-sans text-sm">{m.body}</pre>
                      </details>
                    </li>
                  ))}
                </ul>
              ) : <EmptyState>Nothing sent yet.</EmptyState>}
            </Panel>
          </>
        }
      />
      {po.allowed.send ? <SendDialog po={po} open={sending} onOpenChange={setSending} onSent={setData} /> : null}
    </>
  );
}
