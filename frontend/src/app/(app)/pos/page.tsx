"use client";

/**
 * Purchase orders mirrored from the active ERP connection (PROMPTS Steps 4 and 12). "Sync from ERP" queues
 * a pull job; the page polls the job and reloads the list when it finishes.
 */
import { useState } from "react";
import { CircleCheck, Clock, PackageCheck, PauseCircle, RefreshCw } from "lucide-react";

import { ErpBadge } from "@/components/erp-badge";
import { ErrorNotice, PageHeader } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { StatusPill, type Tone } from "@/components/ui/display";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { api, post } from "@/lib/api";
import { formatDate, formatINR, formatQty } from "@/lib/format";
import type { ActiveErp, Job, PoSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const PO_STATUS: Record<string, { label: string; tone: Tone; icon: typeof Clock }> = {
  open: { label: "To receive", tone: "info", icon: Clock },
  to_bill: { label: "Received, to bill", tone: "warning", icon: PackageCheck },
  completed: { label: "Completed", tone: "success", icon: CircleCheck },
  closed: { label: "Closed", tone: "muted", icon: CircleCheck },
  on_hold: { label: "On hold", tone: "danger", icon: PauseCircle },
};

function Received({ received, ordered }: { received: string; ordered: string }) {
  const share = Number(ordered) > 0 ? Math.min(Number(received) / Number(ordered), 1) : 0;
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden className="h-1.5 w-16 overflow-hidden rounded-full bg-ice">
        <span className="block h-full rounded-full bg-brand-blue" style={{ width: `${share * 100}%` }} />
      </span>
      <span className="tabular-nums">{formatQty(received)} / {formatQty(ordered)}</span>
    </span>
  );
}

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
      if (job.status === "done" && job.result?.purchase_orders) {
        const po = job.result.purchase_orders;
        setState(`Synced from ${job.result.erp ?? "the ERP"}: ${po.created} new, ${po.updated} updated, ${po.unchanged} unchanged POs`);
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
  const erp = useApi<ActiveErp>("/connectors/active").data;
  const canSync = ["admin", "finance", "buyer"].includes(me.role);

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description={erp ? `Read-only mirror of submitted POs and goods receipts in ${erp.name}.`
                         : "Read-only mirror of submitted POs and goods receipts in the connected ERP."}
        actions={canSync ? <SyncButton onDone={reload} /> : undefined}
      />
      {erp ? <p className="-mt-4 mb-4"><ErpBadge label={erp.label} suffix={erp.name} /></p> : null}
      <ErrorNotice message={error} />
      <DataTable rows={data} loading={loading} rowKey={(po) => po.id} noun={["purchase order", "purchase orders"]}
                 rowHref={(po) => `/pos/${po.id}`} initialSort={{ key: "date", dir: "desc" }}
                 empty={canSync ? "No purchase orders yet. Click “Sync from ERP”." : "No purchase orders yet. Ask a buyer or finance to sync from the ERP."}
                 filters={Object.entries(PO_STATUS).slice(0, 3).map(([key, st]) => ({ key, label: st.label, test: (po: PoSummary) => po.status === key }))}
                 columns={[
                   { key: "po", header: "PO", sortValue: (po) => po.erp_ref, searchValue: (po) => `${po.erp_ref} ${po.po_number ?? ""}`,
                     cell: (po) => (
                       <span className="block leading-tight">
                         <span className="font-medium text-primary">{po.erp_ref}</span>
                         {po.po_number && po.po_number !== po.erp_ref ? <span className="mt-0.5 block text-xs text-muted-foreground">PO no. {po.po_number}</span> : null}
                       </span>
                     ) },
                   { key: "vendor", header: "Vendor", sortValue: (po) => po.vendor_name, searchValue: (po) => po.vendor_name, cell: (po) => po.vendor_name ?? "—" },
                   { key: "date", header: "Date", sortValue: (po) => po.po_date, cell: (po) => formatDate(po.po_date) },
                   { key: "status", header: "Status", sortValue: (po) => po.status, cell: (po) => {
                     const st = PO_STATUS[po.status];
                     return st ? <StatusPill tone={st.tone} icon={st.icon}>{st.label}</StatusPill> : <StatusPill>{po.status}</StatusPill>;
                   } },
                   { key: "received", header: "Received / ordered", align: "right", cell: (po) => <Received received={po.qty_received} ordered={po.qty_ordered} /> },
                   { key: "total", header: "Grand total", align: "right", sortValue: (po) => Number(po.grand_total), cell: (po) => <span className="font-medium">{formatINR(po.grand_total)}</span> },
                 ]} />
    </>
  );
}
