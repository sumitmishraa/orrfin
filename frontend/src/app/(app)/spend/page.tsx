"use client";

/**
 * Spend insights (BUILD_PLAN change 49): committed, invoiced and paid side by side, per currency,
 * grouped by vendor, category, cost centre, month or entity. Every figure is a sum of stored records.
 */
import { useState } from "react";
import { Download } from "lucide-react";

import { ErrorNotice, Loading, PageHeader } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
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

function Bar({ value, max, tone = "bg-brand-blue" }: { value: number; max: number; tone?: string }) {
  return <div className="h-1.5 rounded-full bg-ice" aria-hidden><div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${max ? Math.round((value / max) * 100) : 0}%` }} /></div>;
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-white p-4 shadow-raised">
      <p className="text-sm text-muted-foreground">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
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
        <Card label="Invoiced without a PO"><p className="text-xl font-semibold tabular-nums text-heading">{sums(cube.data.no_po_spend)}</p></Card>
        <Card label="Invoiced off contract"><p className="text-xl font-semibold tabular-nums text-heading">{sums(cube.data.off_contract_spend)}</p></Card>
        <Card label="Sourcing savings">
          <ul className="text-sm">{cube.data.sourcing_savings.length === 0 ? <li className="text-muted-foreground">No awarded RFQs yet.</li>
            : cube.data.sourcing_savings.map((sv) => <li key={sv.rfq_id} className="tabular-nums">{sv.arithmetic}</li>)}</ul>
        </Card>
      </div>
      <DataTable rows={cube.data.rows} rowKey={(r) => `${r.group}-${r.currency}`} noun={["group", "groups"]}
                 empty="No spend in this period." initialSort={{ key: "committed", dir: "desc" }}
                 columns={[
                   { key: "group", header: GROUPS.find(([k]) => k === groupBy)?.[1] ?? "Group", sortValue: (r) => r.group, searchValue: (r) => r.group,
                     cell: (r) => <span className="font-medium">{r.group}</span> },
                   { key: "currency", header: "Currency", cell: (r) => r.currency },
                   { key: "committed", header: "Committed", align: "right", sortValue: (r) => Number(r.committed), cell: (r) => r.committed },
                   { key: "invoiced", header: "Invoiced", align: "right", sortValue: (r) => Number(r.invoiced), cell: (r) => r.invoiced },
                   { key: "paid", header: "Paid", align: "right", sortValue: (r) => Number(r.paid), cell: (r) => r.paid },
                   { key: "bars", header: "Committed · invoiced", className: "w-44",
                     cell: (r) => <span className="block space-y-1"><Bar value={Number(r.committed)} max={max} /><Bar value={Number(r.invoiced)} max={max} tone="bg-cyan" /></span> },
                 ]} />
    </div>
  );
}
