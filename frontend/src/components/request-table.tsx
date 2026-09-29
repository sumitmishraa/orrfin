/**
 * A list of purchase requests (Inbox sections, Requests page). Each row links to its detail page.
 */
import Link from "next/link";

import { EmptyState, table } from "@/components/page";
import { StatusBadge } from "@/components/status-badge";
import { formatDate, formatINR, requestNumber } from "@/lib/format";
import type { RequestSummary } from "@/lib/types";

export function RequestTable({ rows, empty }: { rows: RequestSummary[]; empty: string }) {
  if (rows.length === 0) return <EmptyState>{empty}</EmptyState>;
  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th className={table.th}>Request</th>
            <th className={table.th}>Category</th>
            <th className={table.th}>Requested by</th>
            <th className={table.th}>Status</th>
            <th className={table.th}>Waiting on</th>
            <th className={`${table.th} ${table.num}`}>Amount</th>
            <th className={table.th}>Needed by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-ice-light">
              <td className={table.td}>
                <Link href={`/requests/${r.id}`} className="font-medium text-primary hover:underline">
                  {requestNumber(r.number)}
                </Link>
                <p className="text-muted-foreground">{r.title}</p>
              </td>
              <td className={table.td}>{r.category_name}</td>
              <td className={table.td}>{r.requester_name}</td>
              <td className={table.td}><StatusBadge status={r.status} /></td>
              <td className={`${table.td} text-muted-foreground`}>{r.waiting_on ?? "—"}</td>
              <td className={`${table.td} ${table.num} font-medium`}>{formatINR(r.amount)}</td>
              <td className={table.td}>{formatDate(r.needed_by)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
