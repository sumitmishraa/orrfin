"use client";

/**
 * Payments (BUILD_PLAN v2.4 change 31; ADR 0008; PROMPTS Step 25): payment runs, invoices due, and
 * vendor payment details with maker-checker verification. Payments are SIMULATED: an approved run
 * produces a bank file and a mock bank marks it paid; no real money moves.
 */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BadgeCheck, Plus, ShieldAlert } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
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
        <Panel title="Payment runs">
          {runs.loading ? <Loading /> : !runs.data?.length ? <EmptyState>No payment runs yet.</EmptyState> : (
            <div className={table.wrap}><table className={table.table}>
              <thead><tr>{["Run", "Status", "Net to pay", "TDS", "Prepared by", "Approved by", "Created"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
              <tbody>{runs.data.map((r) => (
                <tr key={r.id} className="hover:bg-ice-light">
                  <td className={table.td}><Link href={`/payments/${r.id}`} className="font-medium text-primary hover:underline">{r.label}</Link></td>
                  <td className={table.td}>{RUN_STATUS[r.status] ?? r.status}</td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(r.total_net)}</td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(r.total_tds)}</td>
                  <td className={table.td}>{r.prepared_by}</td>
                  <td className={table.td}>{r.approved_by ?? "—"}</td>
                  <td className={table.td}>{formatDateTime(r.created_at)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Panel>
        <Panel title="Approved invoices with money left to pay">
          {due.loading ? <Loading /> : !due.data?.length ? <EmptyState>Nothing is due.</EmptyState> : (
            <div className={table.wrap}><table className={table.table}>
              <thead><tr>{["Invoice", "Vendor", "Date", "Total", "Left to pay"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
              <tbody>{due.data.map((d) => (
                <tr key={d.invoice_id}>
                  <td className={table.td}><Link href={`/invoices/${d.invoice_id}`} className="text-primary hover:underline">{d.invoice_no}</Link></td>
                  <td className={table.td}>{d.vendor}</td>
                  <td className={table.td}>{formatDate(d.invoice_date)}</td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(d.total)}</td>
                  <td className={`${table.td} ${table.num} font-medium`}>{formatINR(d.left_to_pay)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Panel>
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
