"use client";

/**
 * One purchase order (PROMPTS Step 4): ordered vs received quantity per line, taxes and the
 * goods receipts behind the received figures. Read-only: ERPNext owns POs and receipts (§2).
 */
import { useParams } from "next/navigation";
import { CircleCheck, CircleDot, CircleMinus, PackageCheck } from "lucide-react";

import { AsideCard, BackLink, DetailLayout } from "@/components/detail";
import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { MetaList, PersonCell } from "@/components/ui/display";
import { formatDate, formatINR, formatQty } from "@/lib/format";
import type { PoDetail, PoLine } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function ReceiptState({ line }: { line: PoLine }) {
  const ordered = Number(line.qty);
  const received = Number(line.qty_received);
  if (received >= ordered) {
    return <span className="inline-flex items-center gap-1 text-success"><CircleCheck className="size-3.5" aria-hidden /> Fully received</span>;
  }
  if (received > 0) {
    return <span className="inline-flex items-center gap-1 text-warning"><CircleDot className="size-3.5" aria-hidden /> Partly received</span>;
  }
  return <span className="inline-flex items-center gap-1 text-muted-foreground"><CircleMinus className="size-3.5" aria-hidden /> Not received</span>;
}

export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const { data: po, error, loading } = useApi<PoDetail>(`/purchase-orders/${id}`);

  if (loading) return <Loading />;
  if (error || !po) return <ErrorNotice message={error ?? "Purchase order not found."} />;

  const received = po.lines.filter((l) => Number(l.qty_received) >= Number(l.qty)).length;
  return (
    <>
      <PageHeader
        meta={<BackLink href="/pos" label="Purchase orders" />}
        title={po.erp_ref}
        description={`${po.vendor_name ?? "Unknown vendor"} · read-only mirror from the ERP, which owns POs and receipts`}
      />
      <DetailLayout
        main={
          <Panel title={`Lines · ${received} of ${po.lines.length} fully received`}>
            <div className="-m-4">
        <div className="overflow-x-auto">
          <table className={table.table}>
            <thead>
              <tr>
                <th className={table.th}>#</th>
                <th className={table.th}>Item</th>
                <th className={table.th}>HSN</th>
                <th className={`${table.th} ${table.num}`}>Ordered</th>
                <th className={`${table.th} ${table.num}`}>Received</th>
                <th className={table.th}>Receipt</th>
                <th className={`${table.th} ${table.num}`}>Rate</th>
                <th className={`${table.th} ${table.num}`}>GST</th>
                <th className={`${table.th} ${table.num}`}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {po.lines.map((line) => (
                <tr key={line.id}>
                  <td className={table.td}>{line.line_no}</td>
                  <td className={table.td}>
                    <p>{line.description}</p>
                    <p className="font-mono text-xs text-muted-foreground">{line.item_code}</p>
                  </td>
                  <td className={table.td}>{line.hsn ?? "—"}</td>
                  <td className={`${table.td} ${table.num}`}>{formatQty(line.qty)} {line.uom}</td>
                  <td className={`${table.td} ${table.num} font-medium`}>{formatQty(line.qty_received)}</td>
                  <td className={`${table.td} text-xs`}><ReceiptState line={line} /></td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(line.rate)}</td>
                  <td className={`${table.td} ${table.num}`}>{formatQty(line.tax_rate)}%</td>
                  <td className={`${table.td} ${table.num}`}>{formatINR(line.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
            </div>
          </Panel>
        }
        aside={
          <>
            <AsideCard title="Details">
              <div className="py-2"><PersonCell name={po.vendor_name ?? "Unknown vendor"} detail={po.vendor_gstin ? `GSTIN ${po.vendor_gstin}` : "No GSTIN"} /></div>
              <MetaList rows={[
                { label: "Ordered", value: formatDate(po.po_date) },
                { label: "Due", value: formatDate(po.schedule_date) },
                { label: "Currency", value: po.currency },
                { label: "Last changed in ERP", value: formatDate(po.erp_modified) },
              ]} />
            </AsideCard>
            <AsideCard title="Totals">
              <MetaList rows={[
                { label: "Net total", value: formatINR(po.net_total) },
                { label: "GST", value: formatINR(po.tax_total) },
                { label: "Grand total", value: <span className="text-base font-semibold text-heading">{formatINR(po.grand_total)}</span> },
              ]} />
            </AsideCard>
            <AsideCard title="Goods receipts">
              {po.receipts.length ? (
                <ul className="divide-y divide-border/70 text-sm">
                  {po.receipts.map((r) => (
                    <li key={r.erp_ref} className="flex items-center justify-between gap-3 py-2.5">
                      <span className="flex items-center gap-2 font-medium"><PackageCheck className="size-4 text-success" aria-hidden />{r.erp_ref}</span>
                      <span className="text-muted-foreground">{formatDate(r.posting_date)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="py-2 text-sm text-muted-foreground">Nothing received yet.</p>
              )}
            </AsideCard>
          </>
        }
      />
    </>
  );
}
