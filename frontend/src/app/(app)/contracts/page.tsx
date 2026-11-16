"use client";

/** Contracts list and a quick way to start one (BUILD_PLAN change 44). */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { CircleCheck, CircleDashed, Clock, Plus } from "lucide-react";

import { ErrorNotice, PageHeader } from "@/components/page";
import { DataTable } from "@/components/ui/data-table";
import { StatusPill } from "@/components/ui/display";
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
      <ErrorNotice message={error ?? contracts.error} />
      {["buyer", "finance", "admin"].includes(me.role) ? (
        <div className="flex max-w-xl gap-2 rounded-xl border border-border bg-white p-3 shadow-raised">
          <Input aria-label="New contract title" placeholder="e.g. Office chairs supply 2027" value={title} onChange={(e) => setTitle(e.target.value)} />
          <Button onClick={create} disabled={!title.trim()}><Plus aria-hidden /> New contract</Button>
        </div>
      ) : null}
      <DataTable rows={contracts.data} loading={contracts.loading} rowKey={(c) => c.id} noun={["contract", "contracts"]}
                 rowHref={(c) => `/contracts/${c.id}`} empty="No contracts yet."
                 filters={[{ key: "active", label: "Active", test: (c) => c.status === "active" },
                           { key: "draft", label: "Draft", test: (c) => c.status === "draft" }]}
                 columns={[
                   { key: "title", header: "Contract", sortValue: (c) => c.title, searchValue: (c) => c.title,
                     cell: (c) => <span className="font-medium text-primary">{c.title}</span> },
                   { key: "status", header: "Status", sortValue: (c) => c.status,
                     cell: (c) => <StatusPill tone={c.status === "active" ? "success" : c.status === "draft" ? "muted" : "warning"}
                                              icon={c.status === "active" ? CircleCheck : c.status === "draft" ? CircleDashed : Clock}>
                                    <span className="capitalize">{c.status}</span></StatusPill> },
                   { key: "ends", header: "Ends", sortValue: (c) => c.end_date, cell: (c) => (c.end_date ? formatDate(c.end_date) : "—") },
                 ]} />
    </div>
  );
}
