"use client";

/**
 * Vendors mirrored from the ERP (PROMPTS Step 4). Read-only: ERPNext owns the vendor master (§2).
 */
import { EmptyState, ErrorNotice, Loading, PageHeader, table } from "@/components/page";
import { formatDateTime } from "@/lib/format";
import type { Vendor } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function VendorsPage() {
  const { data, error, loading } = useApi<Vendor[]>("/vendors");
  return (
    <>
      <PageHeader title="Vendors" description="Read-only mirror of the ERP vendor master. Sync from the POs page." />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : !data?.length ? (
        <EmptyState>No vendors yet. Run “Sync from ERP” on the POs page.</EmptyState>
      ) : (
        <div className={table.wrap}>
          <table className={table.table}>
            <thead>
              <tr>
                <th className={table.th}>Vendor</th>
                <th className={table.th}>GSTIN</th>
                <th className={table.th}>State code</th>
                <th className={table.th}>Last changed in ERP</th>
              </tr>
            </thead>
            <tbody>
              {data.map((v) => (
                <tr key={v.id}>
                  <td className={`${table.td} font-medium`}>{v.name}</td>
                  <td className={`${table.td} font-mono text-xs`}>{v.gstin ?? "—"}</td>
                  <td className={table.td}>{v.state_code ?? "—"}</td>
                  <td className={table.td}>{formatDateTime(v.erp_modified)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
