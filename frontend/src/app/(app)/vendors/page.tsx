"use client";

/**
 * Vendors mirrored from the ERP (PROMPTS Step 4). Read-only: ERPNext owns the vendor master (§2).
 */
import { ErrorNotice, PageHeader } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { PersonCell } from "@/components/ui/display";
import { formatDateTime } from "@/lib/format";
import type { Vendor } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function VendorsPage() {
  const { data, error, loading } = useApi<Vendor[]>("/vendors");
  return (
    <>
      <PageHeader title="Vendors" description="Read-only mirror of the ERP vendor master. Sync from the POs page." />
      <ErrorNotice message={error} />
      <DataTable rows={data} loading={loading} rowKey={(v) => v.id} noun={["vendor", "vendors"]}
                 empty="No vendors yet. Run “Sync from ERP” on the Purchase orders page."
                 initialSort={{ key: "name", dir: "asc" }}
                 columns={[
                   { key: "name", header: "Vendor", sortValue: (v) => v.name, searchValue: (v) => `${v.name} ${v.erp_ref}`,
                     cell: (v) => <PersonCell name={v.name} detail={v.erp_ref} /> },
                   { key: "gstin", header: "GSTIN", searchValue: (v) => v.gstin, cell: (v) => <span className="font-mono text-xs">{v.gstin ?? "—"}</span> },
                   { key: "state", header: "State code", sortValue: (v) => v.state_code, cell: (v) => v.state_code ?? "—" },
                   { key: "modified", header: "Last changed in ERP", sortValue: (v) => v.erp_modified, cell: (v) => formatDateTime(v.erp_modified) },
                 ]} />
    </>
  );
}
