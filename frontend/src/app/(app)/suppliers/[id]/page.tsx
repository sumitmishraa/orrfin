"use client";

/**
 * One supplier's onboarding record (BUILD_PLAN change 41-42, §6e): what the supplier entered,
 * the fixed risk rules' findings, and the review decision. The buttons come from the server's
 * `allowed`, worked out with the same rules that enforce the action: the inviter cannot approve,
 * a block stops approval, a hold needs a written reason.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, CircleX, FileText, PauseCircle, TriangleAlert } from "lucide-react";

import { AsideCard, BackLink, DetailLayout } from "@/components/detail";
import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { MetaList, PersonCell, StatusPill } from "@/components/ui/display";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/field";
import { API_URL, post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Finding { rule: string; code: string; kind: "pass" | "hold" | "block"; message: string }
interface SupplierDetail {
  id: string; legal_name: string; country: string; category: string; status: string; contact_name: string; contact_email: string;
  on_hold: boolean; tax_id: string | null; pan: string | null; bank_last4: string | null; vendor_id: string | null;
  answers: Record<string, string>; questions: Record<string, string>;
  invited_by_name: string | null; reviewed_by_name: string | null; review_reason: string | null; submitted_at: string | null;
  documents: { id: string; kind: string; filename: string; expires_on: string | null; uploaded_at: string }[];
  risk: { score: number; level: string; rule_set_version: string; findings: Finding[] };
  allowed: { decide: boolean; decide_blocked_reason: string | null; handover: boolean };
}

const STATUS: Record<string, string> = {
  invited: "Invited, waiting for the supplier", submitted: "Waiting for review", in_review: "In review", approved: "Approved, ready to hand over",
  rejected: "Sent back to the supplier", handed_over: "Waiting to be created in the ERP", active: "Active",
};
const FINDING_ICON = { pass: CircleCheck, hold: TriangleAlert, block: CircleX };
const FINDING_TEXT = { pass: "OK", hold: "Needs a reason", block: "Blocks approval" };

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const supplier = useApi<SupplierDetail>(`/suppliers/${id}`);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (supplier.loading) return <Loading />;
  if (supplier.error || !supplier.data) return <ErrorNotice message={supplier.error ?? "Supplier not found."} />;
  const s = supplier.data;
  const blocks = s.risk.findings.filter((f) => f.kind === "block");

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    try {
      supplier.setData(await post<SupplierDetail>(`/suppliers/${id}/${path}`, body));
      setReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const riskTone = s.risk.level === "low" ? "success" : s.risk.level === "medium" ? "warning" : "danger";

  return (
    <>
      <PageHeader meta={<BackLink href="/suppliers" label="Suppliers" />} title={s.legal_name}
                  description={`Invited by ${s.invited_by_name ?? "someone"}${s.submitted_at ? ` · submitted ${formatDate(s.submitted_at)}` : ""}`}
                  actions={
                    <span className="flex flex-wrap gap-2">
                      <StatusPill tone={s.status === "active" ? "success" : s.status === "rejected" ? "danger" : s.status === "submitted" ? "warning" : "info"}>
                        {STATUS[s.status] ?? s.status}
                      </StatusPill>
                      {s.on_hold ? <StatusPill tone="danger" icon={PauseCircle}>On hold</StatusPill> : null}
                    </span>
                  } />
      <DetailLayout
        aside={
          <>
            <AsideCard title="Supplier">
              <div className="py-2"><PersonCell name={s.contact_name} detail={s.contact_email} /></div>
              <MetaList rows={[
                { label: "Country", value: s.country === "IN" ? "India" : "UAE" },
                { label: "Supplies", value: <span className="capitalize">{s.category}</span> },
                { label: s.country === "IN" ? "GSTIN" : "TRN", value: s.tax_id ? <span className="font-mono text-xs">{s.tax_id}</span> : "Not entered" },
                ...(s.country === "IN" ? [{ label: "PAN", value: s.pan ? <span className="font-mono text-xs">{s.pan}</span> : "Not entered" }] : []),
                { label: "Bank account", value: s.bank_last4 ? `•••• ${s.bank_last4}` : "Not entered" },
              ]} />
              <p className="mt-2 text-xs text-muted-foreground">Bank details are stored encrypted; only the last four digits are ever shown.</p>
            </AsideCard>
            <AsideCard title="Risk" actions={<StatusPill tone={riskTone}><span className="capitalize">{s.risk.level}</span></StatusPill>}>
              <div className="mt-1 flex items-baseline justify-between">
                <span className="text-2xl font-semibold tabular-nums text-heading">{s.risk.score}<span className="text-sm font-normal text-muted-foreground"> / 100</span></span>
                <span className="text-xs text-muted-foreground">rules v{s.risk.rule_set_version}</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-ice" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={s.risk.score} aria-label="Risk score">
                <div className={`h-full rounded-full ${riskTone === "success" ? "bg-success" : riskTone === "warning" ? "bg-warning" : "bg-error"}`} style={{ width: `${s.risk.score}%` }} />
              </div>
              <ul className="mt-4 space-y-2.5 text-sm">
                {s.risk.findings.map((f, i) => {
                  const Icon = FINDING_ICON[f.kind];
                  return (
                    <li key={i} className="flex items-start gap-2">
                      <Icon className={`mt-0.5 size-4 shrink-0 ${f.kind === "pass" ? "text-success" : f.kind === "hold" ? "text-warning" : "text-error"}`} aria-hidden />
                      <span><span className="font-medium">{FINDING_TEXT[f.kind]}:</span> <span className="text-muted-foreground">{f.message}</span></span>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">Worked out by fixed rules, never by AI.</p>
            </AsideCard>
          </>
        }
        main={
          <>
            <ErrorNotice message={error} />
            {s.on_hold ? (
              <div role="alert" className="space-y-2 rounded-xl border border-error/30 bg-error/5 p-4 text-sm">
                <p className="font-medium text-error">On a supplier-risk hold: new purchase orders and payments to this supplier are stopped.</p>
                <p>Finance or an admin (not the person who invited the supplier) can clear it with a reason.</p>
                <Button variant="outline" size="sm" disabled={busy || !reason.trim()} onClick={() => act("clear-hold", { reason })}>Clear the hold with the reason below</Button>
              </div>
            ) : null}

            {s.status === "submitted" || s.on_hold ? (
              <Panel title="Review">
                <div className="space-y-3">
                  {s.allowed.decide_blocked_reason ? <p className="text-sm text-muted-foreground">{s.allowed.decide_blocked_reason}</p> : null}
                  {blocks.length > 0 ? <p className="text-sm text-error">This supplier cannot be approved until the blocking findings are fixed.</p> : null}
                  <Field label="Reason" htmlFor="reason" hint="Needed to reject, to approve despite a finding, or to clear a hold.">
                    <Textarea id="reason" maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
                  </Field>
                  {s.allowed.decide ? (
                    <div className="flex gap-2">
                      <Button disabled={busy || blocks.length > 0} onClick={() => act("decision", { decision: "approve", reason })}>Approve</Button>
                      <Button variant="outline" disabled={busy || !reason.trim()} onClick={() => act("decision", { decision: "reject", reason })}>Send back to the supplier</Button>
                    </div>
                  ) : null}
                </div>
              </Panel>
            ) : null}

            {s.status === "approved" || s.status === "handed_over" || s.status === "active" ? (
              <Panel title="ERP handover">
                <div className="space-y-3 text-sm">
                  {s.reviewed_by_name ? <p>Approved by {s.reviewed_by_name}{s.review_reason ? `: ${s.review_reason}` : "."}</p> : null}
                  {s.status === "approved" ? (
                    <>
                      <p>Orrfin does not create vendors in your ERP. Hand this record over, create the vendor in the ERP with the tax number on the right, and the next sync links it here.</p>
                      {s.allowed.handover ? <Button disabled={busy} onClick={() => act("handover")}>Hand over to the ERP team</Button> : null}
                    </>
                  ) : s.status === "handed_over" ? (
                    <p>Waiting for the vendor to appear in the ERP with tax number <span className="font-mono">{s.tax_id}</span>. Run a sync after it is created.</p>
                  ) : <p>Linked to its ERP vendor. Purchase orders and payments use the ERP vendor record.</p>}
                </div>
              </Panel>
            ) : null}

            <Panel title="Questionnaire">
              {Object.keys(s.questions).length === 0 ? <p className="text-sm text-muted-foreground">No questions answered yet.</p> : (
                <dl className="divide-y divide-border/70 text-sm">
                  {Object.entries(s.questions).map(([key, question]) => (
                    <div key={key} className="flex items-start justify-between gap-4 py-2.5">
                      <dt className="text-foreground">{question}</dt>
                      <dd className="shrink-0 font-medium capitalize">{s.answers[key] ?? "–"}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </Panel>

            <Panel title="Documents">
              {s.documents.length === 0 ? <p className="text-sm text-muted-foreground">Nothing uploaded yet.</p> : (
                <ul className="divide-y divide-border/70 text-sm">
                  {s.documents.map((d) => (
                    <li key={d.id} className="flex flex-wrap items-center gap-3 py-2.5">
                      <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                      <a href={`${API_URL}/suppliers/${s.id}/documents/${d.id}`} className="font-medium capitalize text-primary hover:underline">{d.kind.replaceAll("_", " ")}</a>
                      <span className="min-w-0 flex-1 truncate text-muted-foreground">{d.filename}</span>
                      <span className="text-xs text-muted-foreground">uploaded {formatDate(d.uploaded_at)}{d.expires_on ? ` · valid until ${formatDate(d.expires_on)}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </>
        }
      />
    </>
  );
}
