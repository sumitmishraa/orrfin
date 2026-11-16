"use client";

/**
 * Orders (Step 42, ADR 0012): procurement's workspace in need-first companies.
 * - "Approved needs": every line a manager approved that is not on a purchase order yet, oldest first.
 *   Tick the ones for one vendor (usually a month's worth), then "Create PO".
 * - "Purchase orders": every Orrfin PO with its status, the requests it covers and its ERP number.
 */
import { useState } from "react";
import { Mail, MessageCircle, PackagePlus } from "lucide-react";

import { PageHeader } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/controls";
import { DataTable } from "@/components/ui/data-table";
import { PersonCell } from "@/components/ui/display";
import { formatDate, formatINR, formatQty, requestNumber } from "@/lib/format";
import type { ApprovedNeed, OrderPoSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { NewPoDialog } from "./new-po-dialog";
import { OrderStatus, poNumber } from "./order-status";

const BUILDERS = new Set(["buyer", "admin"]);

function NeedsTable({ canBuild }: { canBuild: boolean }) {
  const needs = useApi<ApprovedNeed[]>("/ordering/needs");
  const [chosen, setChosen] = useState<ApprovedNeed[] | null>(null);
  const thisMonth = new Date().toISOString().slice(0, 7);
  return (
    <>
      <DataTable<ApprovedNeed>
        rows={needs.data}
        loading={needs.loading}
        rowKey={(n) => n.request_line_id}
        noun={["need", "needs"]}
        selectable={canBuild}
        rowHref={(n) => `/requests/${n.request_id}`}
        initialSort={{ key: "needed_by", dir: "asc" }}
        filters={[
          { key: "month", label: "Approved this month", test: (n) => n.approved_at.slice(0, 7) === thisMonth },
          { key: "message", label: "From WhatsApp or email", test: (n) => n.source_channel !== "form" },
        ]}
        bulkActions={(selected, clear) => (
          <Button size="sm" onClick={() => { setChosen(selected); clear(); }}>
            <PackagePlus aria-hidden /> Create PO from {selected.length}
          </Button>
        )}
        empty={<p className="text-sm text-muted-foreground">No approved needs are waiting. When a manager approves a need, it appears here.</p>}
        columns={[
          { key: "item", header: "Item", cell: (n) => (
            <div className="min-w-0">
              <p className="font-medium text-heading">{n.description}</p>
              <p className="text-xs text-muted-foreground">{requestNumber(n.request_number)} · {n.request_title}</p>
            </div>
          ), searchValue: (n) => `${n.description} ${n.request_title} ${requestNumber(n.request_number)}` },
          { key: "qty", header: "Qty", align: "right", cell: (n) => `${formatQty(n.qty)} ${n.unit ?? ""}`, sortValue: (n) => Number(n.qty) },
          { key: "who", header: "Asked by", cell: (n) => (
            <span className="inline-flex items-center gap-1.5">
              <PersonCell name={n.requester_name} size="xs" />
              {n.source_channel === "whatsapp" ? <MessageCircle className="size-3.5 text-muted-foreground" aria-label="via WhatsApp" /> : null}
              {n.source_channel === "email" ? <Mail className="size-3.5 text-muted-foreground" aria-label="via email" /> : null}
            </span>
          ), searchValue: (n) => n.requester_name },
          { key: "category", header: "Kind", cell: (n) => n.category_name, searchValue: (n) => n.category_name },
          { key: "cost_center", header: "Cost centre", cell: (n) => n.cost_center || "—", defaultHidden: true },
          { key: "needed_by", header: "Needed by", cell: (n) => formatDate(n.needed_by), sortValue: (n) => n.needed_by ?? "9999" },
          { key: "approved_at", header: "Approved", cell: (n) => formatDate(n.approved_at), sortValue: (n) => n.approved_at },
        ]}
      />
      {chosen ? <NewPoDialog needs={chosen} open onOpenChange={(open) => { if (!open) setChosen(null); }} /> : null}
    </>
  );
}

function PoTable() {
  const pos = useApi<OrderPoSummary[]>("/ordering/pos");
  return (
    <DataTable<OrderPoSummary>
      rows={pos.data}
      loading={pos.loading}
      rowKey={(p) => p.id}
      noun={["purchase order", "purchase orders"]}
      rowHref={(p) => `/orders/${p.id}`}
      initialSort={{ key: "number", dir: "desc" }}
      filters={[
        { key: "open", label: "Not sent yet", test: (p) => ["draft", "in_approval", "returned", "approved"].includes(p.status) },
        { key: "approval", label: "Waiting for approval", test: (p) => p.status === "in_approval" },
        { key: "sent", label: "Sent", test: (p) => p.status === "sent" },
      ]}
      empty={<p className="text-sm text-muted-foreground">No purchase orders yet. Tick approved needs and press Create PO.</p>}
      columns={[
        { key: "number", header: "PO", cell: (p) => <span className="font-medium text-heading">{poNumber(p.number)}</span>,
          sortValue: (p) => p.number, searchValue: (p) => `${poNumber(p.number)} ${p.erp_doc_name ?? ""}` },
        { key: "vendor", header: "Vendor", cell: (p) => p.vendor_name, searchValue: (p) => p.vendor_name },
        { key: "requests", header: "Covers", cell: (p) => p.requests.join(", ") || "—", searchValue: (p) => p.requests.join(" ") },
        { key: "status", header: "Status", cell: (p) => <OrderStatus status={p.status} />, sortValue: (p) => p.status },
        { key: "erp", header: "ERP number", cell: (p) => p.erp_doc_name ?? "—" },
        { key: "amount", header: "Amount", align: "right", cell: (p) => formatINR(p.amount), sortValue: (p) => Number(p.amount) },
        { key: "needed_by", header: "Deliver by", cell: (p) => formatDate(p.needed_by), defaultHidden: true },
      ]}
    />
  );
}

export default function OrdersPage() {
  const me = useMe();
  const canBuild = BUILDERS.has(me.role);
  const [tab, setTab] = useState(canBuild ? "needs" : "pos");
  if (me.intake_flow !== "need_first") {
    return <PageHeader title="Orders" description="This workspace prices each request on the request itself, so Orders are not used." />;
  }
  return (
    <>
      <PageHeader
        title="Orders"
        description="Approved needs wait here for procurement. Group them by vendor into purchase orders, get them approved, and send them."
      />
      <Tabs value={tab} onValueChange={setTab} tabs={[
        { value: "needs", label: "Approved needs", content: <NeedsTable canBuild={canBuild} /> },
        { value: "pos", label: "Purchase orders", content: <PoTable /> },
      ]} />
    </>
  );
}
