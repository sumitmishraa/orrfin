"use client";

/**
 * New request (PROMPTS Step 5 intake form; Step 24 intake agent). "Describe what you need" asks the
 * intake agent to pre-fill the form: it picks the category and lines; rates come only from past
 * PO prices (or stay blank), and the approval chain shown is the one the server will enforce.
 * Nothing is saved until the person checks the form and presses a button. "Submit" creates the
 * request and routes it to the category's buyer; "Save as draft" keeps it private.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, TriangleAlert } from "lucide-react";

import { ErrorNotice, PageHeader, Panel } from "@/components/page";
import { RequestForm, type RequestFormValues } from "@/components/request-form";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import { formatINR } from "@/lib/format";
import type { RequestDetail } from "@/lib/types";

interface DraftReply {
  available: boolean;
  message?: string;
  draft?: { category_id: string; category: string; title: string; justification: string; cost_center: string;
            needed_by: string | null;
            lines: { description: string; qty: string; est_rate: string | null; rate_source: string }[] };
  amount?: string;
  all_priced?: boolean;
  approval_chain?: string[];
  budget?: { message: string; over: boolean } | null;
  warnings?: string[];
  ai_draft?: { model_id: string; prompt_version: string };
}

function IntakeAgent({ onDraft }: { onDraft: (reply: DraftReply) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function draft() {
    setBusy(true);
    setError(null);
    try {
      const reply = await post<DraftReply>("/assistant/draft-request", { text });
      if (reply.available) onDraft(reply);
      else setError(reply.message ?? "The intake assistant is unavailable.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not draft.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Describe what you need">
      <div className="flex flex-col gap-2">
        <Textarea aria-label="Describe what you need" rows={2} value={text} maxLength={1000}
                  placeholder="e.g. 5 laptops for the new Pune analysts, needed by 1 November, cost centre FIN-OPS"
                  onChange={(e) => setText(e.target.value)} />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" disabled={busy || text.trim().length < 3} onClick={() => void draft()}>
            <Sparkles aria-hidden /> {busy ? "Drafting…" : "Fill the form for me"}
          </Button>
          <span className="text-xs text-muted-foreground">AI fills the form; you check it and press Submit. Prices come only from past purchase orders.</span>
        </div>
        <ErrorNotice message={error} />
      </div>
    </Panel>
  );
}

function DraftSummary({ reply }: { reply: DraftReply }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-cyan/40 bg-ice px-4 py-3 text-sm">
      <p className="font-medium text-heading"><Sparkles className="mr-1 inline size-4" aria-hidden />AI draft: check every field below before you submit.</p>
      <ul className="list-disc pl-5">
        {reply.draft?.lines.map((l, i) => <li key={i}>{l.description} × {l.qty}: {l.est_rate ? formatINR(l.est_rate) : "no price yet"} ({l.rate_source})</li>)}
      </ul>
      <p>
        {reply.all_priced ? "Estimated" : "Priced lines"}: <b>{formatINR(reply.amount)}</b> · approvals needed:{" "}
        <b>{reply.approval_chain?.join(" → ")}</b>
      </p>
      {reply.budget ? <p className={reply.budget.over ? "text-warning" : "text-muted-foreground"}>Budget: {reply.budget.message}</p> : null}
      {reply.warnings?.map((w) => <p key={w} className="flex items-start gap-1.5 text-warning"><TriangleAlert className="mt-0.5 size-3.5" aria-hidden />{w}</p>)}
    </div>
  );
}

export default function NewRequestPage() {
  const router = useRouter();
  const [reply, setReply] = useState<DraftReply | null>(null);
  const [version, setVersion] = useState(0);

  async function create(values: RequestFormValues): Promise<RequestDetail> {
    return post<RequestDetail>("/requests", reply?.ai_draft ? { ...values, ai_draft: reply.ai_draft } : values);
  }

  const prefill: RequestFormValues | undefined = reply?.draft ? {
    category_id: reply.draft.category_id, title: reply.draft.title, justification: reply.draft.justification,
    cost_center: reply.draft.cost_center, needed_by: reply.draft.needed_by, suggested_vendor_id: null,
    lines: reply.draft.lines.map((l) => ({ description: l.description, qty: l.qty, est_rate: l.est_rate ?? "" })),
  } : undefined;

  return (
    <>
      <PageHeader title="New request" description="Describe what you need. Your category's buyer takes it from there." />
      <div className="flex flex-col gap-6">
        <IntakeAgent onDraft={(r) => { setReply(r); setVersion((v) => v + 1); }} />
        {reply ? <DraftSummary reply={reply} /> : null}
        <RequestForm
          key={version}
          prefill={prefill}
          submitLabel="Submit request"
          onSave={async (values) => {
            const created = await create(values);
            await post(`/requests/${created.id}/submit`);
            router.push(`/requests/${created.id}`);
          }}
          secondaryLabel="Save as draft"
          onSecondary={async (values) => {
            const created = await create(values);
            router.push(`/requests/${created.id}`);
          }}
        />
      </div>
    </>
  );
}
