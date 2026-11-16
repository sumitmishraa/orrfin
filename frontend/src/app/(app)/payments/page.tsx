"use client";

/**
 * Payments (BUILD_PLAN v2.4 change 31; ADR 0008; PROMPTS Step 25): payment runs, invoices due, and
 * vendor payment details with maker-checker verification. Payments are SIMULATED: an approved run
 * produces a bank file and a mock bank marks it paid; no real money moves.
 */
import { useState } from "react";

import { useRouter } from "next/navigation";
import { BadgeCheck, Plus, ShieldAlert } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { PersonCell, StatusPill, type Tone } from "@/components/ui/display";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { post, put } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, RUN_STATUS } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface RunRow { id: string; label: string; status: string; total_net: string; total_tds: string; prepared_by: string; approved_by: string | null; created_at: string }
interface Due { invoice_id: string; invoice_no: string; vendor: string; invoice_date: string; total: string; left_to_pay: string }
interface ProfileRow {
  vendor_id: string; vendor: string; gstin: string | null;
  profile: null | { pan: string | null; tds_section: string | null; payee_type: string; account_name: string;
                    bank_account_last4: string; ifsc: string; status: string; changed_by: string | null;
                    verified_by: string | null; can_verify: boolean };
}


const RUN_TONE: Record<string, Tone> = {
  draft: "muted", submitted: "warning", approved: "info", sent: "info", settled: "success", partly_failed: "danger", cancelled: "muted",
};

export default function PaymentsPage() {
  const router = useRouter();
  const runs = useApi<RunRow[]>("/payment-runs");
  const due = useApi<Due[]>("/payments/eligible");
  const [error, setError] = useState<string | null>(null);

  async function newRun() {
    try {
      const currency = window.prompt("Currency for this run (INR, AED, USD or EUR). Invoices are never converted.", "INR");
      if (!currency) return;
      const run = await post<{ id: string }>("/payment-runs", { currency: currency.trim().toUpperCase() });
      router.push(`/payments/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a run.");
    }
  }

  return (
    <>
      <PageHeader title="Payments" description="Simulated payments on synthetic data: an approved run makes a bank file and a mock bank pays it. No real money moves."
                  actions={<Button onClick={() => void newRun()}><Plus aria-hidden /> New payment run</Button>} />
      <ErrorNotice message={error ?? runs.error} />
      <div className="flex flex-col gap-6">
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold text-heading">Payment runs</h2>
          <DataTable rows={runs.data} loading={runs.loading} rowKey={(r) => r.id} noun={["run", "runs"]}
                     rowHref={(r) => `/payments/${r.id}`} empty="No payment runs yet." initialSort={{ key: "created", dir: "desc" }}
                     columns={[
                       { key: "run", header: "Run", sortValue: (r) => r.label, searchValue: (r) => r.label, cell: (r) => <span className="font-medium text-primary">{r.label}</span> },
                       { key: "status", header: "Status", sortValue: (r) => r.status,
                         cell: (r) => <StatusPill tone={RUN_TONE[r.status] ?? "neutral"}>{RUN_STATUS[r.status] ?? r.status}</StatusPill> },
                       { key: "net", header: "Net to pay", align: "right", sortValue: (r) => Number(r.total_net), cell: (r) => <span className="font-medium">{formatINR(r.total_net)}</span> },
                       { key: "tds", header: "TDS", align: "right", sortValue: (r) => Number(r.total_tds), cell: (r) => formatINR(r.total_tds) },
                       { key: "prepared", header: "Prepared by", searchValue: (r) => r.prepared_by, cell: (r) => <PersonCell name={r.prepared_by} size="xs" /> },
                       { key: "approved", header: "Approved by", cell: (r) => (r.approved_by ? <PersonCell name={r.approved_by} size="xs" /> : <span className="text-muted-foreground">—</span>) },
                       { key: "created", header: "Created", sortValue: (r) => r.created_at, cell: (r) => formatDateTime(r.created_at) },
                     ]} />
        </section>
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold text-heading">Approved invoices with money left to pay</h2>
          <DataTable rows={due.data} loading={due.loading} rowKey={(d) => d.invoice_id} noun={["invoice", "invoices"]}
                     rowHref={(d) => `/invoices/${d.invoice_id}`} empty="Nothing is due." initialSort={{ key: "date", dir: "asc" }}
                     columns={[
                       { key: "invoice", header: "Invoice", sortValue: (d) => d.invoice_no, searchValue: (d) => `${d.invoice_no} ${d.vendor}`, cell: (d) => <span className="font-medium text-primary">{d.invoice_no}</span> },
                       { key: "vendor", header: "Vendor", sortValue: (d) => d.vendor, cell: (d) => d.vendor },
                       { key: "date", header: "Date", sortValue: (d) => d.invoice_date, cell: (d) => formatDate(d.invoice_date) },
                       { key: "total", header: "Total", align: "right", sortValue: (d) => Number(d.total), cell: (d) => formatINR(d.total) },
                       { key: "left", header: "Left to pay", align: "right", sortValue: (d) => Number(d.left_to_pay), cell: (d) => <span className="font-semibold">{formatINR(d.left_to_pay)}</span> },
                     ]} />
        </section>
        <VendorProfiles />
      </div>
    </>
  );
}

const BLANK = { pan: "", tds_section: "", payee_type: "company", account_name: "", bank_account: "", ifsc: "" };

function VendorProfiles() {
  const { data, setData, error, loading } = useApi<ProfileRow[]>("/payment-profiles");
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(BLANK);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save(vendorId: string) {
    setSaveError(null);
    try {
      setData(await put<ProfileRow[]>(`/payment-profiles/${vendorId}`, { ...form, pan: form.pan || null, tds_section: form.tds_section || null }));
      setEditing(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  async function verify(vendorId: string) {
    setSaveError(null);
    try {
      setData(await post<ProfileRow[]>(`/payment-profiles/${vendorId}/verify`));
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not verify.");
    }
  }

  return (
    <Panel title="Vendor payment details (bank changes need a second person)">
      <ErrorNotice message={error ?? saveError} />
      {loading ? <Loading /> : (
        <ul className="flex flex-col gap-2 text-sm">
          {data?.map((v) => (
            <li key={v.vendor_id} className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{v.vendor}</span>
                {v.profile ? (
                  <span className="flex items-center gap-2">
                    {v.profile.status === "verified"
                      ? <span className="flex items-center gap-1 text-success"><BadgeCheck className="size-4" aria-hidden /> Verified by {v.profile.verified_by}</span>
                      : <span className="flex items-center gap-1 text-warning"><ShieldAlert className="size-4" aria-hidden /> Changed by {v.profile.changed_by}: needs a second person</span>}
                    {v.profile.can_verify ? <Button size="sm" onClick={() => void verify(v.vendor_id)}>Verify</Button> : null}
                  </span>
                ) : <span className="text-muted-foreground">No payment details</span>}
              </div>
              {v.profile ? (
                <p className="mt-1 text-muted-foreground">
                  {v.profile.account_name} · account {v.profile.bank_account_last4} · {v.profile.ifsc} · PAN {v.profile.pan ?? "missing"} · TDS {v.profile.tds_section ?? "none"}
                </p>
              ) : null}
              {editing === v.vendor_id ? (
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <Input aria-label="Account name" placeholder="Account name" value={form.account_name} onChange={(e) => setForm({ ...form, account_name: e.target.value })} />
                  <Input aria-label="Bank account number" placeholder="Account number" value={form.bank_account} onChange={(e) => setForm({ ...form, bank_account: e.target.value })} />
                  <Input aria-label="IFSC" placeholder="IFSC, e.g. HDFC0001234" value={form.ifsc} onChange={(e) => setForm({ ...form, ifsc: e.target.value })} />
                  <Input aria-label="PAN" placeholder="PAN" value={form.pan} onChange={(e) => setForm({ ...form, pan: e.target.value })} />
                  <Select aria-label="TDS section" value={form.tds_section} onChange={(e) => setForm({ ...form, tds_section: e.target.value })}>
                    <option value="">No TDS</option><option value="194C">194C contractor</option><option value="194J">194J fees</option><option value="194Q">194Q goods</option>
                  </Select>
                  <Select aria-label="Payee type" value={form.payee_type} onChange={(e) => setForm({ ...form, payee_type: e.target.value })}>
                    <option value="company">Company</option><option value="individual">Individual / HUF</option><option value="other">Other</option>
                  </Select>
                  <div className="flex gap-2 sm:col-span-3">
                    <Button size="sm" onClick={() => void save(v.vendor_id)}>Save (needs verification)</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <Button size="sm" variant="outline" className="mt-2" onClick={() => {
                  setEditing(v.vendor_id);
                  setForm({ ...BLANK, account_name: v.profile?.account_name ?? v.vendor, ifsc: v.profile?.ifsc ?? "", pan: v.profile?.pan ?? "",
                            tds_section: v.profile?.tds_section ?? "", payee_type: v.profile?.payee_type ?? "company" });
                }}>{v.profile ? "Change details" : "Add payment details"}</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
