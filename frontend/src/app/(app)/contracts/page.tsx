"use client";

/** Contracts list and a quick way to start one (BUILD_PLAN change 44). */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function ContractsPage() {
  const me = useMe();
  const router = useRouter();
  const contracts = useApi<{ id: string; title: string; status: string; end_date: string | null }[]>("/contracts");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (contracts.loading) return <Loading />;
  if (contracts.error) return <ErrorNotice message={contracts.error} />;

  async function create() {
    try {
      router.push(`/contracts/${(await post<{ id: string }>("/contracts", { title })).id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the contract.");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Contracts" description="Upload a signed contract; key terms are proposed with the quote they came from, and a person confirms each one." />
      <ErrorNotice message={error} />
      {["buyer", "finance", "admin"].includes(me.role) ? (
        <div className="flex max-w-xl gap-2">
          <Input aria-label="New contract title" placeholder="e.g. Office chairs supply 2027" value={title} onChange={(e) => setTitle(e.target.value)} />
          <Button onClick={create} disabled={!title.trim()}><Plus aria-hidden /> New contract</Button>
        </div>
      ) : null}
      {(contracts.data ?? []).length === 0 ? <EmptyState>No contracts yet.</EmptyState> : (
        <div className={table.wrap}><table className={table.table}>
          <thead><tr>{["Contract", "Status", "Ends"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
          <tbody>{contracts.data?.map((c) => (
            <tr key={c.id} className="border-t border-border">
              <td className="px-3 py-2.5"><Link href={`/contracts/${c.id}`} className="font-medium text-heading hover:underline">{c.title}</Link></td>
              <td className="px-3 py-2.5 capitalize">{c.status}</td><td className="px-3 py-2.5">{c.end_date ? formatDate(c.end_date) : "–"}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}
