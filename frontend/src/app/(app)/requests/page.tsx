"use client";

/**
 * Requests list (PROMPTS Step 5): "My requests" for everyone; "All requests" for roles that
 * may see the whole org (a requester only ever gets their own from the API).
 */
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { ErrorNotice, Loading, PageHeader } from "@/components/page";
import { RequestTable } from "@/components/request-table";
import { useMe } from "@/components/session";
import { buttonVariants } from "@/components/ui/button";
import type { RequestSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function RequestsPage() {
  const me = useMe();
  const canSeeAll = me.role !== "requester";
  const [scope, setScope] = useState<"mine" | "all">(canSeeAll ? "all" : "mine");
  const { data, error, loading } = useApi<RequestSummary[]>(`/requests?scope=${scope}`);

  return (
    <>
      <PageHeader
        title="Requests"
        description="Purchase requests from intake to approval."
        actions={
          <Link href="/requests/new" className={buttonVariants({ size: "lg" })}>
            <Plus aria-hidden /> New request
          </Link>
        }
      />
      {canSeeAll ? (
        <div role="tablist" aria-label="Which requests" className="mb-4 inline-flex rounded-lg border border-border bg-white p-1">
          {(["all", "mine"] as const).map((s) => (
            <button key={s} role="tab" aria-selected={scope === s} type="button" onClick={() => setScope(s)}
                    className={`rounded-md px-3 py-1.5 text-sm ${scope === s ? "bg-primary text-primary-foreground" : "text-heading hover:bg-ice"}`}>
              {s === "all" ? "All requests" : "My requests"}
            </button>
          ))}
        </div>
      ) : null}
      <ErrorNotice message={error} />
      {loading ? <Loading /> : <RequestTable rows={data ?? []} empty="No requests yet. Start with “New request”." />}
    </>
  );
}
