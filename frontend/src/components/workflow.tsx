"use client";

/**
 * Workflow pieces shared by several pages (BUILD_PLAN v2.4 changes 29–30; PROMPTS Step 22):
 * the WhatsApp message preview, the reminders panel on a request, and the budget notice.
 * Nothing here sends a message or blocks an action: reminders are recorded in the audit trail,
 * budgets only warn, and the server decides every rule.
 */
import { useState } from "react";
import { BellRing, MessageCircle, TriangleAlert, Wallet, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorNotice, Panel } from "@/components/page";
import { post } from "@/lib/api";
import { formatDateTime, ROLE_LABELS } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export interface Nudge { by: string; at: string }

/** "Step 2: Finance" or the category's own name for its step, e.g. "IT security review". */
export function stepName(step: { required_role: string; step_label?: string | null }): string {
  return step.step_label ?? ROLE_LABELS[step.required_role] ?? step.required_role;
}

export function hoursText(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const h = Number(value);
  return h >= 48 ? `${(h / 24).toFixed(1)} days` : `${value} h`;
}

/** A phone-style card showing the message an approver would get. Never sent: a preview only. */
export function WhatsAppPreview({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const message = text.replace("{origin}", typeof window === "undefined" ? "" : window.location.origin);
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <MessageCircle aria-hidden /> WhatsApp preview
      </Button>
      {open ? (
        <div role="dialog" aria-modal="true" aria-label="WhatsApp message preview"
             className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4"
             onClick={() => setOpen(false)} onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div className="w-full max-w-sm overflow-hidden rounded-[2rem] border-8 border-navy bg-[#e5ddd5] shadow-xl"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between bg-[#075e54] px-4 py-3 text-white">
              <span className="text-sm font-semibold">Orrfin (preview)</span>
              <button type="button" aria-label="Close" onClick={() => setOpen(false)} autoFocus><X className="size-4" /></button>
            </div>
            <div className="p-4">
              <p className="whitespace-pre-wrap rounded-lg rounded-tl-none bg-white p-3 text-sm shadow-sm">
                {message.split("\n").map((line, i) => <span key={i} className={line.startsWith("*") ? "block font-semibold" : line.startsWith("_") ? "block italic text-muted-foreground" : "block"}>{line.replaceAll("*", "").replace(/^_|_$/g, "")}</span>)}
              </p>
              <p className="mt-3 text-center text-xs font-medium text-navy">Preview — not sent. Orrfin sends no messages.</p>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

interface ReminderStatus {
  status: null | { step: number; waiting_on: string; since: string; age_hours: string; sla_hours: number;
                   overdue: boolean; nudges: Nudge[] };
  can_nudge: boolean;
}

/** On a request in approval: how long the current step has waited, and a Nudge when it is overdue. */
export function RemindersPanel({ requestId, version }: { requestId: string; version: string }) {
  const { data, setData, error } = useApi<ReminderStatus>(`/requests/${requestId}/reminders?v=${encodeURIComponent(version)}`);
  const [actionError, setActionError] = useState<string | null>(null);
  if (!data?.status) return error ? <ErrorNotice message={error} /> : null;
  const s = data.status;

  async function nudge() {
    try {
      setData(await post<ReminderStatus>(`/requests/${requestId}/nudge`));
      setActionError(null);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not send the reminder.");
    }
  }

  return (
    <Panel title="Reminders" actions={data.can_nudge ? <Button size="sm" onClick={() => void nudge()}><BellRing aria-hidden /> Nudge</Button> : undefined}>
      <p className={`flex items-center gap-2 text-sm ${s.overdue ? "font-medium text-error" : "text-muted-foreground"}`}>
        {s.overdue ? <TriangleAlert className="size-4" aria-hidden /> : null}
        Step {s.step} ({s.waiting_on}) has waited {hoursText(s.age_hours)}
        {s.overdue ? `, past the ${s.sla_hours} h limit.` : ` of the ${s.sla_hours} h allowed.`}
      </p>
      {s.nudges.length ? (
        <ul className="mt-2 text-sm text-muted-foreground">
          {s.nudges.map((n) => <li key={n.at}>Nudged by {n.by} on {formatDateTime(n.at)} (in the audit trail)</li>)}
        </ul>
      ) : null}
      <ErrorNotice message={actionError} />
    </Panel>
  );
}

export interface BudgetCheck {
  cost_center: string; fiscal_year: string; quarter: number; budget: string; committed: string;
  after: string; pct_after: string | null; over: boolean; message: string;
}

/** The request's effect on its cost centre's budget. A warning only; it never blocks anything. */
export function BudgetNotice({ query }: { query: string | null }) {
  const { data } = useApi<BudgetCheck | null>(query ? `/budgets/check?${query}` : null);
  if (!query || !data) return null;
  return (
    <p className={`flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${data.over ? "border-warning/40 bg-warning/10 text-warning" : "border-border bg-white text-muted-foreground"}`}>
      <Wallet className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span><span className="font-medium">Budget: </span>{data.message}</span>
    </p>
  );
}
