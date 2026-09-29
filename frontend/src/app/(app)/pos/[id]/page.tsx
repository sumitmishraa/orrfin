"use client";

/**
 * One purchase order (PROMPTS Step 4): ordered vs received quantity per line, taxes and the
 * goods receipts behind the received figures. Read-only: ERPNext owns POs and receipts (§2).
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CircleCheck, CircleDot, CircleMinus } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
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

  return (
    <>
      <Link href="/pos" className="mb-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> All purchase orders
      </Link>
      <PageHeader
        title={po.erp_ref}
        description={`${po.vendor_name ?? "Unknown vendor"} · GSTIN ${po.vendor_gstin ?? "—"} · ordered ${formatDate(po.po_date)} · due ${formatDate(po.schedule_date)}`}
      />
      <div className="flex flex-col gap-6">
        <div className={table.wrap}>
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
        <div className="grid gap-6 md:grid-cols-2">
          <Panel title="Totals">
            <dl className="grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Net total</dt><dd className="text-right tabular-nums">{formatINR(po.net_total)}</dd>
              <dt className="text-muted-foreground">GST</dt><dd className="text-right tabular-nums">{formatINR(po.tax_total)}</dd>
              <dt className="font-semibold text-heading">Grand total</dt><dd className="text-right font-semibold tabular-nums text-heading">{formatINR(po.grand_total)}</dd>
            </dl>
          </Panel>
          <Panel title="Goods receipts">
            {po.receipts.length ? (
              <ul className="flex flex-col gap-1 text-sm">
                {po.receipts.map((r) => (
                  <li key={r.erp_ref} className="flex justify-between">
                    <span className="font-medium">{r.erp_ref}</span>
                    <span className="text-muted-foreground">{formatDate(r.posting_date)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Nothing received yet.</p>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
