"use client";

/**
 * My tasks: everything waiting on me, oldest and overdue first (BUILD_PLAN v2.4 change 29; PROMPTS Step 22).
 * Derived live by the server from requests, invoices and questions, so it can never drift.
 * Each task can show the WhatsApp message an approver would receive (a preview; nothing is sent).
 */
import Link from "next/link";
import { CircleCheck, Clock, TriangleAlert } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader } from "@/components/page";
import { hoursText, type Nudge, WhatsAppPreview } from "@/components/workflow";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export interface Task {
  kind: "approval" | "buyer" | "returned" | "exception_task" | "answer" | "invoice"
    | "order" | "po_approval" | "po_send"; // Step 42 (need-first)
  id: string;
  title: string;
  detail: string;
  href: string;
  since: string | null;
  age_hours: string | null;
  overdue: boolean;
  nudges: Nudge[];
  whatsapp: string;
}

const KIND_LABELS: Record<Task["kind"], string> = {
  approval: "Approve",
  buyer: "Complete",
  returned: "Fix and resubmit",
  exception_task: "Answer a question",
  answer: "Answer received",
  invoice: "Decide on an invoice",
  order: "Order approved needs",
  po_approval: "Approve a PO",
  po_send: "Send a PO",
};

export default function TasksPage() {
  const { data, error, loading } = useApi<Task[]>("/tasks");
  return (
    <>
      <PageHeader title="My tasks" description="Everything waiting on you, overdue first. Reminders and answers are recorded in the audit trail." />
      <ErrorNotice message={error} />
      {loading ? <Loading /> : !data?.length ? (
        <EmptyState><CircleCheck className="mx-auto mb-2 size-5 text-success" aria-hidden />Nothing is waiting on you.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {data.map((task) => (
            <li key={`${task.kind}-${task.id}`}
                className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-white p-4 ${task.overdue ? "border-error/40" : "border-border"}`}>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded bg-ice px-2 py-0.5 font-semibold text-heading">{KIND_LABELS[task.kind]}</span>
                  {task.overdue ? (
                    <span className="flex items-center gap-1 font-semibold text-error"><TriangleAlert className="size-3.5" aria-hidden /> Overdue</span>
                  ) : null}
                  {task.age_hours ? (
                    <span className="flex items-center gap-1 text-muted-foreground"><Clock className="size-3.5" aria-hidden /> waiting {hoursText(task.age_hours)}</span>
                  ) : null}
                </div>
                <Link href={task.href} className="mt-1 block font-medium text-primary hover:underline">{task.title}</Link>
                <p className="text-sm text-muted-foreground">{task.detail}</p>
                {task.nudges.length ? (
                  <p className="mt-1 text-xs text-warning">
                    Nudged by {task.nudges.map((n) => `${n.by} (${formatDateTime(n.at)})`).join(", ")}
                  </p>
                ) : null}
              </div>
              <WhatsAppPreview text={task.whatsapp} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
