"use client";

/**
 * Invoice page (PROMPTS Steps 7-9): the PDF on the left, the fields on the right (evidence on hover,
 * failed checks highlighted, editable while under review), then the match result in plain English,
 * the PO / receipt / invoice comparison, and the decision. Buttons come from the server's `allowed`,
 * computed with the same rules that enforce the action (BUILD_PLAN §9).
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CircleAlert, CircleCheck, CircleX, Info, Network, RotateCcw, Sparkles, TriangleAlert } from "lucide-react";

import { InvoiceStatus } from "@/components/invoice-status";
import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { patch, post } from "@/lib/api";
import { formatDateTime, formatINR, formatQty } from "@/lib/format";
import type { InvoiceDetail, InvoiceLine, RuleResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const HEADER_FIELDS: [keyof InvoiceDetail, string][] = [
  ["vendor_name", "Vendor"], ["vendor_gstin", "Vendor GSTIN"], ["invoice_no", "Invoice number"],
  ["invoice_date", "Invoice date (YYYY-MM-DD)"], ["po_reference", "Buyer's PO number"], ["buyer_gstin", "Buyer GSTIN"],
  ["place_of_supply", "Place of supply (state code)"], ["subtotal", "Taxable value (₹)"], ["cgst", "CGST (₹)"],
  ["sgst", "SGST (₹)"], ["igst", "IGST (₹)"], ["total", "Invoice total (₹)"],
];
const LINE_COLS: (keyof InvoiceLine)[] = ["description", "item_code", "hsn", "qty", "rate", "amount"];

function ReviewForm({ invoice, onChange }: { invoice: InvoiceDetail; onChange: (i: InvoiceDetail) => void }) {
  const editable = invoice.allowed.edit;
  const [fields, setFields] = useState<Record<string, string>>(
    Object.fromEntries(HEADER_FIELDS.map(([k]) => [k, (invoice[k] as string | null) ?? ""])),
  );
  const [lines, setLines] = useState(invoice.lines.map((l) => Object.fromEntries(LINE_COLS.map((c) => [c, String(l[c] ?? "")]))));
  const [asPrinted, setAsPrinted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const issueFor = (field: string) => invoice.issues.filter((i) => i.field === field);

  async function act(fn: () => Promise<InvoiceDetail>) {
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
  const save = () => patch<InvoiceDetail>(`/invoices/${invoice.id}`, { fields, lines });

  return (
    <Panel title={editable ? "Check the fields" : "Fields"}>
      <div className="grid gap-3 sm:grid-cols-2">
        {HEADER_FIELDS.map(([key, label]) => {
          const issues = issueFor(key);
          const evidence = invoice.evidence[key];
          return (
            <Field key={key} label={label} htmlFor={`f-${key}`}
                   hint={issues.map((i) => i.message).join(" ") || (evidence ? `Printed: “${evidence.quote}” (page ${evidence.page})` : undefined)}>
              <Input id={`f-${key}`} value={fields[key]} disabled={!editable} aria-invalid={issues.length > 0}
                     title={evidence ? `Evidence on page ${evidence.page}: ${evidence.quote}` : undefined}
                     onChange={(e) => setFields((f) => ({ ...f, [key]: e.target.value }))} />
            </Field>
          );
        })}
      </div>
      <h3 className="mb-2 mt-5 text-sm font-semibold text-heading">Lines</h3>
      <div className={table.wrap}>
        <table className={table.table}>
          <thead><tr>{["Description", "Item code", "HSN", "Qty", "Rate", "Amount"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
          <tbody>
            {lines.map((line, i) => (
              <tr key={i}>
                {LINE_COLS.map((col) => {
                  const bad = issueFor(`lines[${i + 1}].${col}`).length > 0;
                  return (
                    <td key={col} className={table.td}>
                      <Input aria-label={`Line ${i + 1} ${col}`} value={line[col]} disabled={!editable} aria-invalid={bad}
                             className={col === "description" ? "min-w-48" : "w-28"}
                             onChange={(e) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, [col]: e.target.value } : l)))} />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {invoice.issues.length > 0 && editable ? (
        <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning">
          <p className="flex items-center gap-2 font-medium"><TriangleAlert className="size-4" aria-hidden /> {invoice.issues.length} check(s) failed</p>
          <ul className="ml-6 mt-1 list-disc">{invoice.issues.map((i) => <li key={i.field + i.code}>{i.field}: {i.message}</li>)}</ul>
          <label className="mt-2 flex items-center gap-2 text-foreground">
            <input type="checkbox" checked={asPrinted} onChange={(e) => setAsPrinted(e.target.checked)} />
            The document itself is like this: confirm it exactly as printed (the rules will raise exceptions).
          </label>
        </div>
      ) : null}
      <div className="mt-3"><ErrorNotice message={error} /></div>
      {editable ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={() => act(save)}>Save changes</Button>
          {invoice.allowed.confirm ? (
            <Button disabled={busy} onClick={() => act(async () => {
              await save();
              return post<InvoiceDetail>(`/invoices/${invoice.id}/confirm`, { acknowledge_issues: asPrinted });
            })}>Save and confirm for matching</Button>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

const RULE_ICON = { fail: CircleX, warn: CircleAlert, info: Info, pass: CircleCheck };
const RULE_TONE = { fail: "text-error", warn: "text-warning", info: "text-muted-foreground", pass: "text-success" };

function MatchPanel({ invoice, onChange }: { invoice: InvoiceDetail; onChange: (i: InvoiceDetail) => void }) {
  const m = invoice.match!;
  const order = { fail: 0, warn: 1, info: 2, pass: 3 };
  const rules = [...m.rule_results].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <Panel title={`Match result · rules ${m.rule_set_version}`}
           actions={<InvoiceStatus status={m.outcome} />}>
      <div className="flex flex-wrap gap-6 text-sm">
        <p>₹ at risk <span className="ml-1 text-lg font-semibold text-heading">{formatINR(m.amount_at_risk)}</span></p>
        <p>Risk score <span className="ml-1 text-lg font-semibold text-heading">{m.risk_score}/100</span></p>
      </div>
      {m.outcome === "stale" ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning">
          The PO or a goods receipt changed in the ERP after this match. Re-run it before deciding.
          <Button size="sm" variant="outline" onClick={async () => onChange(await post<InvoiceDetail>(`/invoices/${invoice.id}/rematch`))}>
            <RotateCcw aria-hidden /> Re-run match
          </Button>
        </div>
      ) : null}
      {m.explanation ? (
        <div className="mt-4 rounded-lg bg-ice-light p-3 text-sm">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="size-3.5" aria-hidden /> In plain English · {m.explanation_source}
          </p>
          {m.explanation}
        </div>
      ) : null}
      <ul className="mt-4 flex flex-col gap-1.5 text-sm">
        {rules.map((r: RuleResult, i) => {
          const Icon = RULE_ICON[r.status];
          return (
            <li key={i} className="flex gap-2">
              <Icon className={`mt-0.5 size-4 shrink-0 ${RULE_TONE[r.status]}`} aria-hidden />
              <span><span className="sr-only">{r.status}: </span>{r.message}
                {r.status === "fail" && r.amount_at_risk !== "0" && r.amount_at_risk !== "0.00" ? <span className="ml-1 font-medium text-error">({formatINR(r.amount_at_risk)})</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
      {m.po ? (
        <>
          <h3 className="mb-2 mt-5 text-sm font-semibold text-heading">
            PO {m.po.erp_ref} vs receipt vs this invoice <span className="font-normal text-muted-foreground">· {m.po.vendor_name} · {m.po.vendor_gstin}</span>
          </h3>
          <div className={table.wrap}>
            <table className={table.table}>
              <thead><tr>{["PO line", "Item", "PO qty", "Received", "Billed before", "This invoice", "PO rate", "Invoice rate"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
              <tbody>
                {m.comparison.map((c) => (
                  <tr key={c.po_line}>
                    <td className={table.td}>{c.po_line}</td>
                    <td className={table.td}><span className="font-mono text-xs">{c.item_code}</span><p className="text-xs text-muted-foreground">{c.description}</p></td>
                    <td className={`${table.td} ${table.num}`}>{formatQty(c.po_qty)}</td>
                    <td className={`${table.td} ${table.num}`}>{formatQty(c.received)}</td>
                    <td className={`${table.td} ${table.num}`}>{formatQty(c.invoiced_before)}</td>
                    <td className={`${table.td} ${table.num} font-medium`}>{c.invoice_qty ? formatQty(c.invoice_qty) : "—"}</td>
                    <td className={`${table.td} ${table.num}`}>{formatINR(c.po_rate)}</td>
                    <td className={`${table.td} ${table.num}`}>{c.invoice_rate ? formatINR(c.invoice_rate) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {m.unpaired_lines.length ? <p className="mt-2 text-sm text-error">Invoice line(s) {m.unpaired_lines.join(", ")} match no PO line.</p> : null}
        </>
      ) : null}
    </Panel>
  );
}

function DecisionPanel({ invoice, onChange }: { invoice: InvoiceDetail; onChange: (i: InvoiceDetail) => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function decide(decision: "approve" | "reject" | "request_correction") {
    setBusy(true);
    setError(null);
    try {
      onChange(await post<InvoiceDetail>(`/invoices/${invoice.id}/decision`, { decision, reason: reason || null }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed.");
    } finally {
      setBusy(false);
    }
  }
  const blocked = invoice.allowed.approve_blocked_reason;
  return (
    <Panel title="Your decision">
      <Field label={invoice.status === "exception" ? "Reason (required for every decision on an exception)" : "Reason (required to reject or request a correction)"} htmlFor="reason">
        <Textarea id="reason" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {blocked ? <p className="mt-2 text-sm text-warning">You can’t approve: {blocked}</p> : null}
      <div className="mt-2"><ErrorNotice message={error} /></div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled={busy || !!blocked} onClick={() => decide("approve")}><CircleCheck aria-hidden /> Approve {formatINR(invoice.total)}</Button>
        <Button variant="outline" disabled={busy} onClick={() => decide("request_correction")}><RotateCcw aria-hidden /> Request correction</Button>
        <Button variant="destructive" disabled={busy} onClick={() => decide("reject")}><CircleX aria-hidden /> Reject</Button>
      </div>
    </Panel>
  );
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const { data: invoice, setData, error, loading, reload } = useApi<InvoiceDetail>(`/invoices/${id}`);
  const busyStatus = invoice?.status === "extracting" || invoice?.status === "matching";

  useEffect(() => {
    // The worker reads and matches in the background: refresh until it is done.
    if (!busyStatus) return;
    const timer = setInterval(() => void reload(), 2000);
    return () => clearInterval(timer);
  }, [busyStatus, reload]);

  if (loading) return <Loading />;
  if (error || !invoice) return <ErrorNotice message={error ?? "Invoice not found."} />;

  return (
    <>
      <PageHeader
        title={invoice.invoice_no ?? invoice.filename}
        description={`${invoice.vendor_name ?? "Vendor not read yet"} · uploaded by ${invoice.uploaded_by_name}${invoice.confirmed_by_name ? ` · confirmed by ${invoice.confirmed_by_name}` : ""}`}
        actions={
          <div className="flex items-center gap-3">
            <InvoiceStatus status={invoice.outcome === "stale" ? "stale" : invoice.status} />
            <Link href={`/control-graph?invoice_id=${invoice.id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
              <Network className="size-4" aria-hidden /> Control Graph
            </Link>
          </div>
        }
      />
      {invoice.extraction?.simulated ? (
        <p className="mb-4 rounded-lg border border-border bg-ice px-3 py-2 text-sm text-heading">
          Simulated reading: these fields come from the evaluation answer key (AI_PROVIDER=fake), not from an AI model.
        </p>
      ) : null}
      {invoice.status === "manual_entry" ? (
        <p className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          The AI could not read this invoice after 3 tries, so it is in manual entry: type the fields from the PDF.
          {invoice.extraction_error ? ` (${invoice.extraction_error})` : ""}
        </p>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-2">
        <iframe title="Invoice PDF" src={`/api/invoices/${invoice.id}/file`} className="h-[80vh] w-full rounded-xl border border-border bg-white" />
        <div className="flex flex-col gap-6">
          {invoice.status === "extracting" ? <Loading label="Reading the invoice…" /> : (
            <ReviewForm key={invoice.timeline.length} invoice={invoice} onChange={setData} />
          )}
          {invoice.status === "matching" ? <Loading label="Checking against the PO and receipt…" /> : null}
          {invoice.match ? <MatchPanel invoice={invoice} onChange={setData} /> : null}
          {invoice.allowed.decide ? <DecisionPanel invoice={invoice} onChange={setData} /> : null}
          {invoice.decisions.length ? (
            <Panel title="Decisions">
              <ul className="flex flex-col gap-1 text-sm">
                {invoice.decisions.map((d, i) => (
                  <li key={i}><span className="font-medium">{d.decision.replace("_", " ")}</span> by {d.reviewer_name} · {formatDateTime(d.at)}{d.reason ? ` · “${d.reason}”` : ""}</li>
                ))}
              </ul>
            </Panel>
          ) : null}
          <Panel title="History">
            <ol className="flex flex-col gap-2 text-sm">
              {invoice.timeline.map((e) => (
                <li key={e.seq}><span className="font-medium text-heading">{e.action.replaceAll("_", " ")}</span>
                  <span className="text-muted-foreground"> · {e.actor_name ?? "System"} · {formatDateTime(e.at)}</span></li>
              ))}
            </ol>
            {invoice.edits.length ? (
              <p className="mt-3 text-xs text-muted-foreground">
                Field edits: {invoice.edits.map((e) => `${e.field}: ${e.old ?? "∅"} → ${e.new ?? "∅"} (${e.edited_by_name})`).join(" · ")}
              </p>
            ) : null}
          </Panel>
        </div>
      </div>
    </>
  );
}
