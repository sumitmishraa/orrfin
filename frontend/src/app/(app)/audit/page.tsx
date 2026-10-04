"use client";

/**
 * Audit (BUILD_PLAN §2 audit trail, §11 M5; PROMPTS Step 9): every invoice and request with its
 * timeline, and a hash-chain check that shows whether any past event was altered.
 */
import { useState } from "react";
import Link from "next/link";
import { Network, ShieldCheck, ShieldX } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { formatDateTime } from "@/lib/format";
import type { AuditEntity, AuditTrail } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function Trail({ entityId }: { entityId: string }) {
  const { data, error, loading, reload } = useApi<AuditTrail>(`/audit/${entityId}`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNotice message={error ?? "Not found."} />;
  const graphParam = data.entity_type === "invoice" ? "invoice_id" : "request_id";
  return (
    <Panel title={data.label} actions={
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => void reload()}
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${data.chain_valid ? "bg-success/10 text-success" : "bg-error/10 text-error"}`}>
          {data.chain_valid ? <ShieldCheck className="size-3.5" aria-hidden /> : <ShieldX className="size-3.5" aria-hidden />}
          {data.chain_valid ? "Chain verified" : "Chain broken: history was altered"} · verify again
        </button>
        <Link href={`/control-graph?${graphParam}=${data.entity_id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          <Network className="size-4" aria-hidden /> Control Graph
        </Link>
      </div>
    }>
      <ol className="flex flex-col gap-2 text-sm">
        {data.events.map((e) => (
          <li key={e.seq} className="flex flex-wrap gap-x-2">
            <span className="w-6 text-right text-muted-foreground">{e.seq}</span>
            <span className="font-medium text-heading">{e.action.replaceAll("_", " ")}</span>
            <span className="text-muted-foreground">{e.actor_name ?? "System"} · {formatDateTime(e.at)}</span>
            <span className="font-mono text-xs text-muted-foreground" title="This event's fingerprint">#{e.hash.slice(0, 10)}</span>
          </li>
        ))}
      </ol>
    </Panel>
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
      {loading ? <Loading /> : !data?.length ? <EmptyState>No history yet.</EmptyState> : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className={table.wrap}>
            <table className={table.table}>
              <thead><tr>{["Record", "Status", "Events", "Last change"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
              <tbody>
                {data.map((e) => (
                  <tr key={e.entity_id} className={`cursor-pointer hover:bg-ice-light ${selected === e.entity_id ? "bg-ice" : ""}`}
                      onClick={() => setSelected(e.entity_id)}>
                    <td className={table.td}>
                      <button type="button" className="text-left font-medium text-primary hover:underline">{e.label}</button>
                      <p className="text-xs text-muted-foreground">{e.entity_type === "invoice" ? "Invoice" : "Purchase request"}</p>
                    </td>
                    <td className={table.td}>{e.status.replaceAll("_", " ")}</td>
                    <td className={`${table.td} ${table.num}`}>{e.events}</td>
                    <td className={table.td}>{e.last_action.replaceAll("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected ? <Trail key={selected} entityId={selected} /> : <EmptyState>Choose a record to see its timeline and verify its chain.</EmptyState>}
        </div>
      )}
    </>
  );
}
