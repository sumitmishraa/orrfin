"use client";

/**
 * Inbox: everything waiting for the logged-in user, by role (PROMPTS Step 5):
 * approvals they can act on, the buyer queue, the admin queue, and their own drafts/returns.
 */
import Link from "next/link";
import { Plus } from "lucide-react";

import { RequestTable } from "@/components/request-table";
import { useMe } from "@/components/session";
import { buttonVariants } from "@/components/ui/button";
import { InvoiceTable } from "@/components/invoice-table";
import { ErrorNotice, PageHeader } from "@/components/page";
import type { InvoiceSummary, RequestSummary } from "@/lib/types";
import { useApi } from "@/lib/use-api";

function Section({ title, path, empty, filter }: {
  title: string;
  path: string;
  empty: string;
  filter?: (r: RequestSummary) => boolean;
}) {
  const { data, error, loading } = useApi<RequestSummary[]>(path);
  const rows = data ? data.filter(filter ?? (() => true)) : null;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold text-heading">
        {title} {rows ? <span className="font-normal text-muted-foreground">· {rows.length}</span> : null}
      </h2>
      <ErrorNotice message={error} />
      <RequestTable rows={rows} loading={loading} empty={empty} compact />
    </section>
  );
}

function InvoiceSection({ title, path, empty }: { title: string; path: string; empty: string }) {
  const { data, error, loading } = useApi<InvoiceSummary[]>(path);
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold text-heading">
        {title} {data ? <span className="font-normal text-muted-foreground">· {data.length}</span> : null}
      </h2>
      <ErrorNotice message={error} />
      <InvoiceTable rows={data} loading={loading} empty={empty} compact sortByRisk />
    </section>
  );
}

export default function InboxPage() {
  const me = useMe();
  return (
    <>
      <PageHeader
        title={`Good day, ${me.full_name.split(" ")[0]}`}
        description="Everything waiting for you."
        actions={
          <Link href="/requests/new" className={buttonVariants({ size: "lg" })}>
            <Plus aria-hidden /> New request
          </Link>
        }
      />
      <div className="flex flex-col gap-8">
        {me.role === "finance" || me.role === "admin" ? (
          <>
            <InvoiceSection title="Exceptions, largest ₹ at risk first" path="/invoices?scope=exceptions"
                            empty="No invoice exceptions waiting." />
            <InvoiceSection title="Invoices to check" path="/invoices?scope=review"
                            empty="No invoices waiting for their fields to be checked." />
          </>
        ) : null}
        {me.role !== "requester" && me.role !== "buyer" ? (
          <Section title="Waiting for your approval" path="/requests?scope=approvals"
                   empty="Nothing needs your approval right now." />
        ) : null}
        {me.role === "buyer" ? (
          <Section title="Your buyer queue" path="/requests?scope=buyer_queue"
                   empty="No requests are waiting for you to complete." />
        ) : null}
        {me.role === "admin" ? (
          <Section title="Needs a buyer (admin queue)" path="/requests?scope=admin_queue"
                   empty="Every submitted request has a buyer." />
        ) : null}
        <Section title="Your requests needing action" path="/requests?scope=mine"
                 filter={(r) => r.status === "draft" || r.status === "returned"}
                 empty="None of your requests are drafts or returned to you." />
      </div>
    </>
  );
}
