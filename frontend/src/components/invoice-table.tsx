"use client";

/**
 * A list of supplier invoices (Invoices page, Inbox sections) on the shared DataTable (Step 41).
 * ₹ at risk is shown in red with its amount, never colour alone; each row opens the invoice.
 */
import type { ReactNode } from "react";

import { InvoiceStatus } from "@/components/invoice-status";
import { DataTable, type Column } from "@/components/ui/data-table";
import { formatDate, formatINR } from "@/lib/format";
import type { InvoiceSummary } from "@/lib/types";

const atRisk = (inv: InvoiceSummary) => Boolean(inv.amount_at_risk && inv.amount_at_risk !== "0.00");

const COLUMNS: Column<InvoiceSummary>[] = [
  {
    key: "invoice", header: "Invoice", sortValue: (i) => i.invoice_date ?? i.created_at,
    searchValue: (i) => `${i.invoice_no ?? ""} ${i.filename}`,
    cell: (i) => (
      <span className="block leading-tight">
        <span className="font-medium text-primary">{i.invoice_no ?? i.filename}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{formatDate(i.invoice_date ?? i.created_at)}</span>
      </span>
    ),
  },
  { key: "vendor", header: "Vendor", sortValue: (i) => i.vendor_name, searchValue: (i) => i.vendor_name, cell: (i) => i.vendor_name ?? "—" },
  { key: "po", header: "PO", searchValue: (i) => i.po_reference, cell: (i) => <span className="font-mono text-xs">{i.po_reference ?? "—"}</span> },
  { key: "status", header: "Status", sortValue: (i) => i.status, cell: (i) => <InvoiceStatus status={i.outcome === "stale" ? "stale" : i.status} /> },
  { key: "total", header: "Total", align: "right", sortValue: (i) => Number(i.total ?? 0), cell: (i) => formatINR(i.total) },
  {
    key: "risk", header: "At risk", align: "right", sortValue: (i) => Number(i.amount_at_risk ?? 0),
    cell: (i) => atRisk(i) ? <span className="font-semibold text-error">{formatINR(i.amount_at_risk)}</span> : <span className="text-muted-foreground">—</span>,
  },
];

export function InvoiceTable({ rows, loading = false, empty, actions, compact = false, sortByRisk = false }: {
  rows: InvoiceSummary[] | null;
  loading?: boolean;
  empty: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
  sortByRisk?: boolean;
}) {
  return (
    <DataTable rows={rows} loading={loading} columns={COLUMNS} rowKey={(i) => i.id} noun={["invoice", "invoices"]}
               rowHref={(i) => `/invoices/${i.id}`} empty={empty} actions={actions} bare={compact}
               initialSort={sortByRisk ? { key: "risk", dir: "desc" } : { key: "invoice", dir: "desc" }}
               filters={compact ? undefined : [
                 { key: "exception", label: "Exceptions", test: (i) => i.status === "exception" || atRisk(i) },
                 { key: "check", label: "To check", test: (i) => ["needs_review", "manual_entry", "correction_requested"].includes(i.status) },
                 { key: "matched", label: "Matched", test: (i) => i.status === "matched" },
                 { key: "approved", label: "Approved", test: (i) => i.status === "approved" },
               ]} />
  );
}
