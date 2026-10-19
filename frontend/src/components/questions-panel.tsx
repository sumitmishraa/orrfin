"use client";

/**
 * Questions on a held invoice (BUILD_PLAN v2.4 change 29; PROMPTS Step 22) — Zip's exception task:
 * finance holds the invoice and asks a named person (often the requester); while the question is
 * open nobody can approve it, and the person asked can never approve it. Both sides are audited.
 */
import { useState } from "react";
import { MessageSquareText } from "lucide-react";

import { ErrorNotice, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { InvoiceDetail } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export interface ExceptionTasksView {
  tasks: { id: string; asked_by: string; assigned_to: string; assigned_to_id: string; question: string;
           answer: string | null; status: "open" | "answered" | "closed"; asked_at: string;
           answered_at: string | null; can_answer: boolean }[];
  can_ask: boolean;
  suggested_assignee_id: string | null;
}

const STATUS_TEXT = { open: "Waiting for an answer", answered: "Answered", closed: "Closed with the decision" };

export function QuestionsPanel({ invoice, onChange }: { invoice: InvoiceDetail; onChange: (i: InvoiceDetail) => void }) {
  const view = invoice.exception_tasks as ExceptionTasksView | null;
  const { data: people } = useApi<{ id: string; full_name: string; role: string }[]>(view?.can_ask ? "/users" : null);
  const [assignee, setAssignee] = useState(view?.suggested_assignee_id ?? "");
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  if (!view || (!view.can_ask && !view.tasks.length)) return null;

  async function act(fn: () => Promise<InvoiceDetail>) {
    setError(null);
    try {
      onChange(await fn());
      setQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    }
  }

  return (
    <Panel title="Questions (hold and ask)">
      <div className="flex flex-col gap-4">
        {view.tasks.map((t) => (
          <div key={t.id} className="rounded-lg border border-border p-3 text-sm">
            <p className="flex items-start gap-2">
              <MessageSquareText className="mt-0.5 size-4 shrink-0 text-heading" aria-hidden />
              <span><b>{t.asked_by}</b> asked <b>{t.assigned_to}</b> · {formatDateTime(t.asked_at)}: “{t.question}”</span>
            </p>
            {t.answer ? <p className="mt-2 pl-6">Answer · {t.answered_at ? formatDateTime(t.answered_at) : ""}: “{t.answer}”</p> : null}
            <p className={`mt-1 pl-6 text-xs ${t.status === "open" ? "text-warning" : "text-muted-foreground"}`}>{STATUS_TEXT[t.status]}</p>
            {t.can_answer ? (
              <div className="mt-2 flex flex-col gap-2 pl-6">
                <Textarea aria-label="Your answer" rows={2} value={answers[t.id] ?? ""}
                          onChange={(e) => setAnswers({ ...answers, [t.id]: e.target.value })} />
                <Button size="sm" className="self-start" disabled={!(answers[t.id] ?? "").trim()}
                        onClick={() => void act(() => post<InvoiceDetail>(`/exception-tasks/${t.id}/answer`, { answer: answers[t.id] }))}>
                  Send answer
                </Button>
              </div>
            ) : null}
          </div>
        ))}
        {view.can_ask ? (
          <div className="grid gap-3">
            <p className="text-sm text-muted-foreground">Ask someone before deciding. Approval waits until they answer, and they cannot approve this invoice.</p>
            <Field label="Ask" htmlFor="ask-who">
              <Select id="ask-who" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                <option value="">Choose a person</option>
                {(people ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.full_name} ({p.role}){p.id === view.suggested_assignee_id ? " · requested this purchase" : ""}</option>
                ))}
              </Select>
            </Field>
            <Field label="Question" htmlFor="ask-what">
              <Textarea id="ask-what" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)}
                        placeholder="e.g. The price is 7% above the PO. Did we agree a new rate?" />
            </Field>
            <Button size="sm" className="self-start" disabled={!assignee || !question.trim()}
                    onClick={() => void act(() => post<InvoiceDetail>(`/invoices/${invoice.id}/questions`, { assigned_to: assignee, question }))}>
              Hold and ask
            </Button>
          </div>
        ) : null}
        <ErrorNotice message={error} />
      </div>
    </Panel>
  );
}
