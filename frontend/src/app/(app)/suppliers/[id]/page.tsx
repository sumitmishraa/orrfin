"use client";

/**
 * One supplier's onboarding record (BUILD_PLAN change 41-42, §6e): what the supplier entered,
 * the fixed risk rules' findings, and the review decision. The buttons come from the server's
 * `allowed`, worked out with the same rules that enforce the action: the inviter cannot approve,
 * a block stops approval, a hold needs a written reason.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
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
  invited: "Invited, waiting for the supplier", submitted: "Waiting for review", approved: "Approved, ready to hand over",
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

  return (
    <div className="space-y-6">
      <PageHeader title={s.legal_name} description={`${STATUS[s.status] ?? s.status} · invited by ${s.invited_by_name ?? "someone"}`} />
      <ErrorNotice message={error} />

      {s.on_hold ? (
        <div role="alert" className="space-y-2 rounded-xl border border-error/30 bg-error/5 p-4 text-sm">
          <p className="font-medium text-error">On a supplier-risk hold: new purchase orders and payments to this supplier are stopped.</p>
          <p>Finance or an admin (not the person who invited the supplier) can clear it with a reason.</p>
          <Button variant="outline" size="sm" disabled={busy || !reason.trim()} onClick={() => act("clear-hold", { reason })}>Clear the hold with the reason below</Button>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="What the supplier entered">
          <dl className="grid grid-cols-[10rem_1fr] gap-y-2 p-4 text-sm">
            <dt className="text-muted-foreground">Country</dt><dd>{s.country === "IN" ? "India" : "United Arab Emirates"}</dd>
            <dt className="text-muted-foreground">Supplies</dt><dd className="capitalize">{s.category}</dd>
            <dt className="text-muted-foreground">Contact</dt><dd>{s.contact_name} ({s.contact_email})</dd>
            <dt className="text-muted-foreground">{s.country === "IN" ? "GSTIN" : "TRN"}</dt><dd className="font-mono">{s.tax_id ?? "Not entered"}</dd>
            {s.country === "IN" ? <><dt className="text-muted-foreground">PAN</dt><dd className="font-mono">{s.pan ?? "Not entered"}</dd></> : null}
            <dt className="text-muted-foreground">Bank account</dt><dd>{s.bank_last4 ? `Ending ${s.bank_last4} (full number is encrypted)` : "Not entered"}</dd>
            {Object.entries(s.questions).map(([key, question]) => (
              <div key={key} className="col-span-2 grid grid-cols-[1fr_4rem] gap-2 border-t border-border pt-2">
                <dt>{question}</dt><dd className="font-medium capitalize">{s.answers[key] ?? "–"}</dd>
              </div>
            ))}
          </dl>
        </Panel>

        <Panel title={`Risk: ${s.risk.level} (score ${s.risk.score} of 100)`}>
          <div className="space-y-3 p-4 text-sm">
            <p className="text-muted-foreground">Worked out by fixed rules (version {s.risk.rule_set_version}), never by AI.</p>
            <ul className="space-y-2">
              {s.risk.findings.map((f, i) => {
                const Icon = FINDING_ICON[f.kind];
                return (
                  <li key={i} className="flex items-start gap-2">
                    <Icon className={`mt-0.5 size-4 shrink-0 ${f.kind === "pass" ? "text-success" : f.kind === "hold" ? "text-warning" : "text-error"}`} aria-hidden />
                    <span><span className="font-medium">{FINDING_TEXT[f.kind]}:</span> {f.message}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </Panel>
      </div>

      <Panel title="Documents">
        {s.documents.length === 0 ? <p className="p-4 text-sm text-muted-foreground">Nothing uploaded yet.</p> : (
          <ul className="space-y-1 p-4 text-sm">
            {s.documents.map((d) => (
              <li key={d.id}>
                <a href={`${API_URL}/suppliers/${s.id}/documents/${d.id}`} className="font-medium text-primary underline">{d.kind.replace("_", " ")}</a>
                {" "}· {d.filename} · uploaded {formatDate(d.uploaded_at)}{d.expires_on ? ` · valid until ${formatDate(d.expires_on)}` : ""}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {s.status === "submitted" || s.on_hold ? (
        <Panel title="Review">
          <div className="space-y-3 p-4">
            {s.allowed.decide_blocked_reason ? <p className="text-sm text-muted-foreground">{s.allowed.decide_blocked_reason}</p> : null}
            {blocks.length > 0 ? <p className="text-sm text-error">This supplier cannot be approved until the blocking findings above are fixed.</p> : null}
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
          <div className="space-y-3 p-4 text-sm">
            {s.reviewed_by_name ? <p>Approved by {s.reviewed_by_name}{s.review_reason ? `: ${s.review_reason}` : "."}</p> : null}
            {s.status === "approved" ? (
              <>
                <p>Orrfin does not create vendors in your ERP. Hand this record over, create the vendor in the ERP with the tax number above, and the next sync links it here.</p>
                {s.allowed.handover ? <Button disabled={busy} onClick={() => act("handover")}>Hand over to the ERP team</Button> : null}
              </>
            ) : s.status === "handed_over" ? (
              <p>Waiting for the vendor to appear in the ERP with tax number <span className="font-mono">{s.tax_id}</span>. Run a sync after it is created.</p>
            ) : <p>Linked to its ERP vendor. Purchase orders and payments use the ERP vendor record.</p>}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
