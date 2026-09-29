"use client";

/**
 * Purchase orders mirrored from the ERP (PROMPTS Step 4). "Sync from ERP" queues a pull job;
 * the page polls the job and reloads the list when it finishes.
 */
import { useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { api, post } from "@/lib/api";
import { formatDate, formatINR, formatQty } from "@/lib/format";
import type { Job, PoSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const PO_STATUS: Record<string, string> = {
  open: "To receive",
  to_bill: "Received, to bill",
  completed: "Completed",
  closed: "Closed",
  on_hold: "On hold",
};

function SyncButton({ onDone }: { onDone: () => void }) {
  const [state, setState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function sync() {
    setBusy(true);
    setError(null);
    setState("Queued…");
    try {
      let job = await post<Job>("/sync/erp");
      // The worker usually finishes within a second or two; stop waiting after ~30 s.
      for (let i = 0; i < 30 && (job.status === "queued" || job.status === "running"); i++) {
        await new Promise((r) => setTimeout(r, 1000));
        job = await api<Job>(`/jobs/${job.id}`);
        setState(job.status === "running" ? "Syncing…" : "Queued…");
      }
      if (job.status === "done" && job.result) {
        const po = job.result.purchase_orders;
        setState(`Synced: ${po.created} new, ${po.updated} updated, ${po.unchanged} unchanged POs`);
        onDone();
      } else if (job.status === "failed") {
        setError(`Sync failed: ${job.last_error}`);
        setState(null);
      } else {
        setError("The sync is still waiting. Is the worker running? (scripts\\dev.ps1 starts it.)");
        setState(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed.");
      setState(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button size="lg" onClick={sync} disabled={busy}>
        <RefreshCw className={busy ? "animate-spin" : undefined} aria-hidden /> Sync from ERP
      </Button>
      {state ? <p className="text-xs text-muted-foreground" role="status">{state}</p> : null}
      {error ? <div className="max-w-sm"><ErrorNotice message={error} /></div> : null}
    </div>
  );
}

export default function PurchaseOrdersPage() {
  const me = useMe();
  const { data, error, loading, reload } = useApi<PoSummary[]>("/purchase-orders");
  const canSync = ["admin", "finance", "buyer"].includes(me.role);

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="Read-only mirror of submitted POs and goods receipts in ERPNext (fake ERPNext until Step 11)."
        actions={canSync ? <SyncButton onDone={reload} /> : undefined}
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : !data?.length ? (
        <EmptyState>No purchase orders yet. {canSync ? "Click “Sync from ERP”." : "Ask a buyer or finance to sync from the ERP."}</EmptyState>
      ) : (
        <div className={table.wrap}>
          <table className={table.table}>
            <thead>
              <tr>
                <th className={table.th}>PO</th>
                <th className={table.th}>Vendor</th>
                <th className={table.th}>Date</th>
                <th className={table.th}>Status</th>
                <th className={`${table.th} ${table.num}`}>Received / ordered</th>
                <th className={`${table.th} ${table.num}`}>Grand total</th>
              </tr>
            </thead>
            <tbody>
              {data.map((po) => (
                <tr key={po.id} className="hover:bg-ice-light">
                  <td className={table.td}>
                    <Link href={`/pos/${po.id}`} className="font-medium text-primary hover:underline">{po.erp_ref}</Link>
                  </td>
                  <td className={table.td}>{po.vendor_name ?? "—"}</td>
                  <td className={table.td}>{formatDate(po.po_date)}</td>
                  <td className={table.td}>{PO_STATUS[po.status] ?? po.status}</td>
                  <td className={`${table.td} ${table.num}`}>{formatQty(po.qty_received)} / {formatQty(po.qty_ordered)}</td>
                  <td className={`${table.td} ${table.num} font-medium`}>{formatINR(po.grand_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
