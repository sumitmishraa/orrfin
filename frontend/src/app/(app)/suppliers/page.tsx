"use client";

/**
 * Supplier onboarding list (BUILD_PLAN change 41). Buyers, finance and admins invite a supplier;
 * the supplier fills in the portal; finance or an admin (never the inviter) reviews.
 * Orrfin does not create the vendor in the ERP: after approval a person does, and the sync links it.
 */
import { useState } from "react";
import { CircleCheck, Clock, Copy, Hourglass, PauseCircle, Send, Undo2, UserPlus } from "lucide-react";

import { ErrorNotice, PageHeader, Panel } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { PersonCell, StatusPill, type Tone } from "@/components/ui/display";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface SupplierRow { id: string; legal_name: string; country: string; category: string; status: string; contact_name: string; on_hold: boolean; updated_at: string }

const SUPPLIER_STATUS: Record<string, { label: string; tone: Tone; icon: typeof Clock }> = {
  invited: { label: "Invited, waiting for the supplier", tone: "muted", icon: Send },
  submitted: { label: "Waiting for review", tone: "warning", icon: Hourglass },
  in_review: { label: "In review", tone: "warning", icon: Hourglass },
  approved: { label: "Approved, ready to hand over", tone: "info", icon: CircleCheck },
  rejected: { label: "Sent back to the supplier", tone: "danger", icon: Undo2 },
  handed_over: { label: "Waiting to be created in the ERP", tone: "info", icon: Clock },
  active: { label: "Active", tone: "success", icon: CircleCheck },
};
const BLANK = { legal_name: "", country: "IN", category: "goods", contact_name: "", contact_email: "" };

export default function SuppliersPage() {
  const me = useMe();
  const suppliers = useApi<SupplierRow[]>("/suppliers");
  const [form, setForm] = useState<typeof BLANK | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      <ErrorNotice message={error ?? suppliers.error} />

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

      <DataTable rows={suppliers.data} loading={suppliers.loading} rowKey={(r) => r.id} noun={["supplier", "suppliers"]}
                 rowHref={(r) => `/suppliers/${r.id}`} initialSort={{ key: "updated", dir: "desc" }}
                 empty="No suppliers yet. Invite one to start onboarding."
                 filters={[
                   { key: "review", label: "Waiting for review", test: (r) => r.status === "submitted" || r.status === "in_review" },
                   { key: "invited", label: "Invited", test: (r) => r.status === "invited" },
                   { key: "active", label: "Active", test: (r) => r.status === "active" },
                   { key: "hold", label: "On hold", test: (r) => r.on_hold },
                 ]}
                 columns={[
                   { key: "name", header: "Supplier", sortValue: (r) => r.legal_name, searchValue: (r) => `${r.legal_name} ${r.contact_name}`,
                     cell: (r) => <PersonCell name={r.legal_name} detail={r.contact_name} /> },
                   { key: "country", header: "Country", sortValue: (r) => r.country, cell: (r) => (r.country === "IN" ? "India" : "UAE") },
                   { key: "category", header: "Supplies", sortValue: (r) => r.category, cell: (r) => <span className="capitalize">{r.category}</span> },
                   { key: "status", header: "Status", sortValue: (r) => r.status, cell: (r) => {
                     const st = SUPPLIER_STATUS[r.status];
                     return (
                       <span className="flex flex-wrap gap-1.5">
                         {st ? <StatusPill tone={st.tone} icon={st.icon}>{st.label}</StatusPill> : <StatusPill>{r.status}</StatusPill>}
                         {r.on_hold ? <StatusPill tone="danger" icon={PauseCircle}>On hold</StatusPill> : null}
                       </span>
                     );
                   } },
                   { key: "updated", header: "Updated", sortValue: (r) => r.updated_at, cell: (r) => formatDate(r.updated_at) },
                 ]} />
    </div>
  );
}
