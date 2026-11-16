"use client";

/**
 * Audit (BUILD_PLAN §2 audit trail, §11 M5; PROMPTS Step 9): every invoice and request with its
 * timeline, and a hash-chain check that shows whether any past event was altered.
 */
import { useState } from "react";
import Link from "next/link";
import { Network, ShieldCheck, ShieldX } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { StatusPill } from "@/components/ui/display";
import { Sheet } from "@/components/ui/overlay";
import { useMe } from "@/components/session";
import { formatDateTime } from "@/lib/format";
import type { AuditEntity, AuditTrail } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function Trail({ entityId, onClose }: { entityId: string; onClose: () => void }) {
  const { data, error, loading, reload } = useApi<AuditTrail>(`/audit/${entityId}`);
  const graphParam = data?.entity_type === "invoice" ? "invoice_id" : "request_id";
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()} title={data?.label ?? "History"}
           description="Every event in order. Each one carries the fingerprint of the one before it."
           header={data ? (
             <div className="flex flex-wrap items-center gap-3 pb-3">
               <button type="button" onClick={() => void reload()} title="Verify the chain again">
                 {data.chain_valid
                   ? <StatusPill tone="success" icon={ShieldCheck}>Chain verified · check again</StatusPill>
                   : <StatusPill tone="danger" icon={ShieldX}>Chain broken: history was altered</StatusPill>}
               </button>
               <Link href={`/control-graph?${graphParam}=${data.entity_id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                 <Network className="size-4" aria-hidden /> Control Graph
               </Link>
             </div>
           ) : undefined}>
      {loading ? <Loading /> : error || !data ? <ErrorNotice message={error ?? "Not found."} /> : (
        <ol className="relative space-y-4 border-l border-border pl-5 text-sm">
          {data.events.map((e) => (
            <li key={e.seq} className="relative">
              <span aria-hidden className="absolute -left-[25px] top-1.5 size-2.5 rounded-full border-2 border-white bg-brand-bright ring-1 ring-border" />
              <p className="font-medium capitalize text-heading">{e.action.replaceAll("_", " ")}</p>
              <p className="text-xs text-muted-foreground">
                #{e.seq} · {e.actor_name ?? "System"} · {formatDateTime(e.at)} ·{" "}
                <span className="font-mono" title="This event's fingerprint">{e.hash.slice(0, 10)}</span>
              </p>
            </li>
          ))}
        </ol>
      )}
    </Sheet>
  );
}

export default function AuditPage() {
  const me = useMe();
  const allowed = ["approver", "finance", "admin"].includes(me.role);
  const { data, error, loading } = useApi<AuditEntity[]>(allowed ? "/audit/entities" : null);
  const [selected, setSelected] = useState<string | null>(null);

  if (!allowed) return (<><PageHeader title="Audit" /><EmptyState>The audit trail is open to approvers, finance and admins.</EmptyState></>);
  return (
    <>
      <PageHeader title="Audit" description="Every change, with who and when. Each record's history is hash-chained, so tampering shows." />
      <ErrorNotice message={error} />
      <DataTable rows={data} loading={loading} rowKey={(e) => e.entity_id} noun={["record", "records"]}
                 onRowClick={(e) => setSelected(e.entity_id)} empty="No history yet."
                 filters={[{ key: "invoice", label: "Invoices", test: (e) => e.entity_type === "invoice" },
                           { key: "request", label: "Requests", test: (e) => e.entity_type !== "invoice" }]}
                 columns={[
                   { key: "record", header: "Record", sortValue: (e) => e.label, searchValue: (e) => e.label,
                     cell: (e) => (
                       <span className="block leading-tight">
                         <span className="font-medium text-primary">{e.label}</span>
                         <span className="mt-0.5 block text-xs text-muted-foreground">{e.entity_type === "invoice" ? "Invoice" : "Purchase request"}</span>
                       </span>
                     ) },
                   { key: "status", header: "Status", sortValue: (e) => e.status, cell: (e) => <StatusPill><span className="capitalize">{e.status.replaceAll("_", " ")}</span></StatusPill> },
                   { key: "events", header: "Events", align: "right", sortValue: (e) => e.events, cell: (e) => e.events },
                   { key: "last", header: "Last change", searchValue: (e) => e.last_action, cell: (e) => <span className="capitalize text-muted-foreground">{e.last_action.replaceAll("_", " ")}</span> },
                 ]} />
      {selected ? <Trail key={selected} entityId={selected} onClose={() => setSelected(null)} /> : null}
    </>
  );
}
