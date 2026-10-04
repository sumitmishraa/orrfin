"use client";

/**
 * Control Graph (BUILD_PLAN §1 step 13, §13 demo step 8; PROMPTS Step 10): the whole chain for one
 * invoice or one request, request → approvals → PO → receipt → invoice → match → decision → ERP draft.
 * Every box is clickable through to the page that holds its detail.
 */
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CircleCheck, CircleDashed, CircleDot, CircleMinus, CircleX } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader } from "@/components/page";
import type { GraphNode } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const STATE = {
  done: { icon: CircleCheck, tone: "border-success/40 bg-success/5", text: "Done" },
  current: { icon: CircleDot, tone: "border-warning/50 bg-warning/5", text: "In progress" },
  blocked: { icon: CircleX, tone: "border-error/40 bg-error/5", text: "Stopped" },
  pending: { icon: CircleDashed, tone: "border-dashed border-border bg-white", text: "Not yet" },
  skipped: { icon: CircleMinus, tone: "border-dashed border-border bg-ice-light", text: "Does not apply" },
};
const KIND_LABEL: Record<string, string> = {
  request: "Intake", approval: "Approval", po: "Purchase order", receipt: "Goods receipt", invoice: "Invoice",
  match: "Rules", decision: "Human decision", erp_draft: "ERP draft",
};

function Graph() {
  const params = useSearchParams();
  const query = params.get("invoice_id") ? `invoice_id=${params.get("invoice_id")}` : params.get("request_id") ? `request_id=${params.get("request_id")}` : null;
  const { data, error, loading } = useApi<{ subject: string; nodes: GraphNode[] }>(query ? `/control-graph?${query}` : null);

  if (!query) return <EmptyState>Open the Control Graph from an invoice or a request page.</EmptyState>;
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNotice message={error ?? "Not found."} />;
  return (
    <ol className="flex flex-wrap items-stretch gap-2" aria-label="Control chain">
      {data.nodes.map((node, i) => {
        const s = STATE[node.state];
        const body = (
          <div className={`flex h-full w-52 flex-col gap-1 rounded-xl border p-3 transition-shadow ${s.tone} ${node.href ? "hover:shadow-md" : ""}`}>
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <s.icon className="size-3.5" aria-hidden /> {KIND_LABEL[node.kind] ?? node.kind} · {s.text}
            </p>
            <p className="text-sm font-semibold text-heading">{node.label}</p>
            {node.detail ? <p className="text-xs text-muted-foreground">{node.detail}</p> : null}
          </div>
        );
        return (
          <li key={i} className="flex items-center gap-2">
            {node.href ? <Link href={node.href} className="h-full">{body}</Link> : body}
            {i < data.nodes.length - 1 ? <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
          </li>
        );
      })}
    </ol>
  );
}

export default function ControlGraphPage() {
  return (
    <>
      <PageHeader title="Control Graph" description="Every handoff from the need to the draft bill, with who did what. Click a box for its detail." />
      <Suspense fallback={<Loading />}>
        <Graph />
      </Suspense>
    </>
  );
}
