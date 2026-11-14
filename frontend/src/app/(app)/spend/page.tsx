"use client";

/**
 * Spend insights (BUILD_PLAN change 49): committed, invoiced and paid side by side, per currency,
 * grouped by vendor, category, cost centre, month or entity. Every figure is a sum of stored records.
 */
import { useState } from "react";
import { Download } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { API_URL } from "@/lib/api";
import { useApi } from "@/lib/use-api";

interface Cube {
  rows: { group: string; currency: string; committed: string; invoiced: string; paid: string }[];
  no_po_spend: Record<string, string>; off_contract_spend: Record<string, string>; notes: string[];
  sourcing_savings: { rfq_id: string; saving: string; arithmetic: string }[];
}
const GROUPS = [["vendor", "Vendor"], ["category", "Category"], ["cost_center", "Cost centre"], ["month", "Month"], ["entity", "Legal entity"]];

function Bar({ value, max }: { value: number; max: number }) {
  return <div className="h-2 rounded bg-ice" aria-hidden><div className="h-2 rounded bg-primary" style={{ width: `${max ? Math.round((value / max) * 100) : 0}%` }} /></div>;
}

export default function SpendPage() {
  const [groupBy, setGroupBy] = useState("vendor");
  const cube = useApi<Cube>(`/spend?group_by=${groupBy}`);

  if (cube.loading) return <Loading />;
  if (cube.error || !cube.data) return <ErrorNotice message={cube.error ?? "Could not load spend."} />;
  const max = Math.max(0, ...cube.data.rows.map((r) => Number(r.committed)), ...cube.data.rows.map((r) => Number(r.invoiced)));
  const sums = (m: Record<string, string>) => Object.entries(m).map(([c, v]) => `${c} ${v}`).join(" · ") || "None";

  return (
    <div className="space-y-6">
      <PageHeader title="Spend insights" description={cube.data.notes[0]}
        actions={<span className="flex gap-2">
          <a href={`${API_URL}/spend/export.csv?group_by=${groupBy}`}><Button variant="outline"><Download aria-hidden /> CSV</Button></a>
          <a href={`${API_URL}/spend/export.pdf?group_by=${groupBy}`}><Button variant="outline"><Download aria-hidden /> PDF</Button></a>
        </span>} />
      <Select aria-label="Group spend by" value={groupBy} onChange={(e) => setGroupBy(e.target.value)} className="max-w-xs">
        {GROUPS.map(([k, label]) => <option key={k} value={k}>By {label.toLowerCase()}</option>)}
      </Select>
      <div className="grid gap-4 sm:grid-cols-3">
        <Panel title="Invoiced without a PO"><p className="p-4 text-lg font-semibold tabular-nums">{sums(cube.data.no_po_spend)}</p></Panel>
        <Panel title="Invoiced off contract"><p className="p-4 text-lg font-semibold tabular-nums">{sums(cube.data.off_contract_spend)}</p></Panel>
        <Panel title="Sourcing savings">
          <ul className="p-4 text-sm">{cube.data.sourcing_savings.length === 0 ? <li className="text-muted-foreground">No awarded RFQs yet.</li>
            : cube.data.sourcing_savings.map((s) => <li key={s.rfq_id} className="tabular-nums">{s.arithmetic}</li>)}</ul>
        </Panel>
      </div>
      {cube.data.rows.length === 0 ? <EmptyState>No spend in this period.</EmptyState> : (
        <div className={table.wrap}><table className={table.table}>
          <thead><tr>{["Group", "Currency", "Committed", "Invoiced", "Paid", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
          <tbody>{cube.data.rows.map((r) => (
            <tr key={`${r.group}-${r.currency}`} className="border-t border-border">
              <td className="px-3 py-2.5 font-medium">{r.group}</td><td className="px-3 py-2.5">{r.currency}</td>
              <td className="px-3 py-2.5 tabular-nums">{r.committed}</td><td className="px-3 py-2.5 tabular-nums">{r.invoiced}</td>
              <td className="px-3 py-2.5 tabular-nums">{r.paid}</td>
              <td className="w-40 px-3 py-2.5"><Bar value={Number(r.committed)} max={max} /><div className="mt-1"><Bar value={Number(r.invoiced)} max={max} /></div></td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}
