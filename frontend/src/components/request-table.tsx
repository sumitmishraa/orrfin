"use client";

/**
 * A list of purchase requests (Inbox sections, Requests page) on the shared DataTable (Step 41):
 * search, status filters, sorting and paging. Each row opens the request.
 */
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/status-badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { PersonCell } from "@/components/ui/display";
import { formatDate, formatINR, requestNumber } from "@/lib/format";
import type { RequestSummary } from "@/lib/types";

const OPEN = ["submitted", "with_buyer", "in_approval", "returned"];

const COLUMNS: Column<RequestSummary>[] = [
  {
    key: "request", header: "Request", sortValue: (r) => r.number,
    searchValue: (r) => `${requestNumber(r.number)} ${r.title}`,
    cell: (r) => (
      <span className="block min-w-0 leading-tight">
        <span className="font-medium text-primary">{requestNumber(r.number)}</span>
        <span className="mt-0.5 block max-w-[28ch] truncate text-muted-foreground">{r.title}</span>
      </span>
    ),
  },
  { key: "requester", header: "Requested by", sortValue: (r) => r.requester_name, searchValue: (r) => r.requester_name,
    cell: (r) => <PersonCell name={r.requester_name} size="sm" /> },
  { key: "category", header: "Category", sortValue: (r) => r.category_name, searchValue: (r) => r.category_name, cell: (r) => r.category_name },
  { key: "status", header: "Status", sortValue: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
  { key: "waiting", header: "Waiting on", searchValue: (r) => r.waiting_on,
    cell: (r) => <span className="text-muted-foreground">{r.waiting_on ?? "—"}</span> },
  { key: "amount", header: "Amount", align: "right", sortValue: (r) => Number(r.amount),
    cell: (r) => <span className="font-medium">{formatINR(r.amount)}</span> },
  { key: "needed", header: "Needed by", sortValue: (r) => r.needed_by, cell: (r) => formatDate(r.needed_by) },
];

export function RequestTable({ rows, empty, loading = false, actions, compact = false }: {
  rows: RequestSummary[] | null;
  empty: ReactNode;
  loading?: boolean;
  actions?: ReactNode;
  /** A short list inside a page section: no toolbar or paging. */
  compact?: boolean;
}) {
  return (
    <DataTable rows={rows} loading={loading} columns={COLUMNS} rowKey={(r) => r.id} noun={["request", "requests"]}
               rowHref={(r) => `/requests/${r.id}`} empty={empty} actions={actions} bare={compact}
               initialSort={{ key: "request", dir: "desc" }}
               filters={compact ? undefined : [
                 { key: "open", label: "Open", test: (r) => OPEN.includes(r.status) },
                 { key: "approved", label: "Approved", test: (r) => ["approved", "po_drafted", "po_open"].includes(r.status) },
                 { key: "draft", label: "Drafts", test: (r) => r.status === "draft" },
                 { key: "closed", label: "Rejected or cancelled", test: (r) => ["rejected", "cancelled"].includes(r.status) },
               ]} />
  );
}
