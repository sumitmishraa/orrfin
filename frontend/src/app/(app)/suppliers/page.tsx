"use client";

/**
 * Supplier onboarding list (BUILD_PLAN change 41). Buyers, finance and admins invite a supplier;
 * the supplier fills in the portal; finance or an admin (never the inviter) reviews.
 * Orrfin does not create the vendor in the ERP: after approval a person does, and the sync links it.
 */
import { useState } from "react";
import Link from "next/link";
import { Copy, UserPlus } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface SupplierRow { id: string; legal_name: string; country: string; category: string; status: string; contact_name: string; on_hold: boolean; updated_at: string }

const SUPPLIER_STATUS: Record<string, string> = {
  invited: "Invited, waiting for the supplier", submitted: "Waiting for review", approved: "Approved, ready to hand over",
  rejected: "Sent back to the supplier", handed_over: "Waiting to be created in the ERP", active: "Active",
};
const BLANK = { legal_name: "", country: "IN", category: "goods", contact_name: "", contact_email: "" };

export default function SuppliersPage() {
  const me = useMe();
  const suppliers = useApi<SupplierRow[]>("/suppliers");
  const [form, setForm] = useState<typeof BLANK | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (suppliers.loading) return <Loading />;
  if (suppliers.error) return <ErrorNotice message={suppliers.error} />;
  const canInvite = ["buyer", "finance", "admin"].includes(me.role);

  async function invite() {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const created = await post<{ invite_link: string }>("/suppliers/invites", form);
      setLink(created.invite_link);
      setForm(null);
      await suppliers.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the invitation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Suppliers"
        description="Invite a new supplier, check their details and hand them over to your ERP."
        actions={canInvite && !form ? <Button onClick={() => setForm(BLANK)}><UserPlus aria-hidden /> Invite a supplier</Button> : undefined}
      />
      <ErrorNotice message={error} />

      {link ? (
        <div role="status" className="space-y-2 rounded-lg border border-primary/40 bg-ice p-3 text-sm">
          <p className="font-medium text-heading">Invitation created. Send this link to the supplier: it works once, for 7 days, and is not shown again.</p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all rounded bg-white px-2 py-1">{link}</code>
            <Button variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(link)}><Copy aria-hidden /> Copy</Button>
            <Button size="sm" onClick={() => setLink(null)}>Done</Button>
          </div>
        </div>
      ) : null}

      {form ? (
        <Panel title="Invite a supplier">
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Supplier's legal name" htmlFor="s-name">
              <Input id="s-name" maxLength={200} value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
            </Field>
            <Field label="Country" htmlFor="s-country">
              <Select id="s-country" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
                <option value="IN">India</option>
                <option value="AE">United Arab Emirates</option>
              </Select>
            </Field>
            <Field label="What they supply" htmlFor="s-category">
              <Select id="s-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="goods">Goods</option>
                <option value="services">Services</option>
                <option value="software">Software</option>
              </Select>
            </Field>
            <Field label="Contact person" htmlFor="s-contact">
              <Input id="s-contact" maxLength={200} value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
            </Field>
            <Field label="Contact's email" htmlFor="s-email">
              <Input id="s-email" type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </Field>
            <div className="flex items-end gap-2">
              <Button onClick={invite} disabled={busy || !form.legal_name || !form.contact_name || !form.contact_email}>Create invitation</Button>
              <Button variant="outline" onClick={() => setForm(null)} disabled={busy}>Cancel</Button>
            </div>
          </div>
        </Panel>
      ) : null}

      {(suppliers.data ?? []).length === 0 ? <EmptyState>No suppliers yet. Invite one to start onboarding.</EmptyState> : (
        <div className={table.wrap}>
          <table className={table.table}>
            <thead>
              <tr>{["Supplier", "Country", "Supplies", "Status", "Updated"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {suppliers.data?.map((s) => (
                <tr key={s.id} className="border-t border-border">
                  <td className="px-3 py-2.5">
                    <Link href={`/suppliers/${s.id}`} className="font-medium text-heading hover:underline">{s.legal_name}</Link>
                    {s.on_hold ? <span className="ml-2 rounded-full bg-error/10 px-2 py-0.5 text-xs font-medium text-error">On hold</span> : null}
                  </td>
                  <td className="px-3 py-2.5">{s.country === "IN" ? "India" : "UAE"}</td>
                  <td className="px-3 py-2.5 capitalize">{s.category}</td>
                  <td className="px-3 py-2.5">{SUPPLIER_STATUS[s.status] ?? s.status}</td>
                  <td className="px-3 py-2.5">{formatDate(s.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
