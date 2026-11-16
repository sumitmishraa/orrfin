"use client";

/**
 * New request (PROMPTS Step 5 intake form; Step 24 intake agent; Step 42 need-first intake).
 *
 * Two ways in:
 * - "Fill the form": the person types the need (or asks the intake agent to fill the form from a sentence).
 * - "Paste a WhatsApp / email message" (Step 42): employees often send their needs to the manager on
 *   WhatsApp or by email. Paste the message; Orrfin reads the items and quantities out of it (with AI when
 *   it is available, or a simple "number + item" reading when it is not) and keeps the message word for
 *   word on the request, so the manager approves exactly what was asked.
 * Nothing is saved until the person checks the form and presses a button. A manager or procurement
 * entering a need for an employee saves it as the employee's draft; the employee submits it.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, MessageCircle, Sparkles, TriangleAlert } from "lucide-react";

import { ErrorNotice, PageHeader, Panel } from "@/components/page";
import { RequestForm, toPayload, type RequestFormValues } from "@/components/request-form";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/controls";
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

type Channel = "whatsapp" | "email";
const RAISERS = new Set(["approver", "buyer", "finance", "admin"]);

/**
 * Reads "20 boxes of A4 paper, 5 box files" style lines without AI: a number, an optional unit word,
 * then the item. Only a starting point: the person checks every line before saving.
 */
function readMessage(text: string): RequestFormValues["lines"] {
  // A unit word counts only when it is plural or followed by "of": "20 boxes of paper" has a unit,
  // "5 box files" is five box files.
  const UNIT = /^(?:(boxes|pcs|pieces|nos|packs|reams|kg|litres|sets|units)\b\s*(?:of\s+)?|(box|pack|ream|set|litre)\s+of\s+)/i;
  const out: RequestFormValues["lines"] = [];
  for (const part of text.split(/\n|,|;| and /i)) {
    const match = part.match(/(\d+(?:\.\d+)?)\s*(?:x\s*)?([A-Za-z].*)/);
    if (!match) continue;
    let rest = match[2].trim();
    const unit = rest.match(UNIT);
    if (unit) rest = rest.slice(unit[0].length);
    rest = rest.replace(/\b(by|before|for the|thanks|regards)\b.*$/i, "").replace(/[.!]+$/, "").trim();
    if (rest.length < 2) continue;
    const unitWord = unit ? (unit[1] ?? unit[2]).toLowerCase() : "";
    out.push({ description: rest.charAt(0).toUpperCase() + rest.slice(1), qty: match[1], est_rate: "",
               unit: unitWord === "boxes" ? "box" : unitWord.replace(/s$/, "") });
  }
  return out.slice(0, 20);
}

function MessageIntake({ onRead }: { onRead: (channel: Channel, text: string, reply: DraftReply | null) => void }) {
  const [channel, setChannel] = useState<Channel>("whatsapp");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function read() {
    setBusy(true);
    try {
      const reply = await post<DraftReply>("/assistant/draft-request", { text: text.slice(0, 1000) });
      onRead(channel, text, reply.available ? reply : null);
    } catch {
      onRead(channel, text, null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Paste the message">
      <div className="flex flex-col gap-3">
        <div role="radiogroup" aria-label="Where the message came from" className="flex gap-2">
          {([["whatsapp", "WhatsApp", MessageCircle], ["email", "Email", Mail]] as const).map(([value, label, Icon]) => (
            <button key={value} type="button" role="radio" aria-checked={channel === value}
                    onClick={() => setChannel(value)}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm ${
                      channel === value ? "border-primary bg-ice font-medium text-heading" : "border-border bg-white text-muted-foreground"}`}>
              <Icon className="size-4" aria-hidden /> {label}
            </button>
          ))}
        </div>
        <Textarea aria-label="The message" rows={5} value={text} maxLength={4000}
                  placeholder={channel === "whatsapp"
                    ? "e.g. Hi Neha, we need 20 boxes of A4 paper and 5 box files for the Pune office by 30 Nov. Thanks, Riya"
                    : "Paste the email text here"}
                  onChange={(e) => setText(e.target.value)} />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" disabled={busy || text.trim().length < 3} onClick={() => void read()}>
            <Sparkles aria-hidden /> {busy ? "Reading…" : "Read the message"}
          </Button>
          <span className="text-xs text-muted-foreground">
            Orrfin fills the form from the message and keeps the message on the request. You check everything first.
          </span>
        </div>
      </div>
    </Panel>
  );
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
          <span className="text-xs text-muted-foreground">AI fills the form; you check it and press the button below.</span>
        </div>
        <ErrorNotice message={error} />
      </div>
    </Panel>
  );
}

function DraftSummary({ reply, needFirst }: { reply: DraftReply; needFirst: boolean }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-cyan/40 bg-ice px-4 py-3 text-sm">
      <p className="font-medium text-heading"><Sparkles className="mr-1 inline size-4" aria-hidden />AI draft: check every field below before you submit.</p>
      <ul className="list-disc pl-5">
        {reply.draft?.lines.map((l, i) => (
          <li key={i}>{l.description} × {l.qty}{needFirst ? "" : `: ${l.est_rate ? formatINR(l.est_rate) : "no price yet"} (${l.rate_source})`}</li>
        ))}
      </ul>
      <p>
        {needFirst ? null : <>{reply.all_priced ? "Estimated" : "Priced lines"}: <b>{formatINR(reply.amount)}</b> · </>}
        approvals needed: <b>{reply.approval_chain?.join(" → ")}</b>
      </p>
      {reply.budget && !needFirst ? <p className={reply.budget.over ? "text-warning" : "text-muted-foreground"}>Budget: {reply.budget.message}</p> : null}
      {reply.warnings?.filter((w) => !needFirst || !w.includes("past price")).map((w) => (
        <p key={w} className="flex items-start gap-1.5 text-warning"><TriangleAlert className="mt-0.5 size-3.5" aria-hidden />{w}</p>
      ))}
    </div>
  );
}

function OriginalMessage({ channel, text }: { channel: Channel; text: string }) {
  const Icon = channel === "whatsapp" ? MessageCircle : Mail;
  return (
    <section className="rounded-xl border border-border bg-white p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" aria-hidden /> The {channel === "whatsapp" ? "WhatsApp message" : "email"} (saved on the request)
      </p>
      <p className="mt-2 whitespace-pre-wrap rounded-lg bg-ice-light px-3 py-2 text-sm text-heading">{text}</p>
    </section>
  );
}

export default function NewRequestPage() {
  const router = useRouter();
  const me = useMe();
  const needFirst = me.intake_flow === "need_first";
  const canRaiseForOthers = needFirst && RAISERS.has(me.role);
  const [mode, setMode] = useState<"form" | "message">("form");
  const [reply, setReply] = useState<DraftReply | null>(null);
  const [source, setSource] = useState<{ channel: Channel; text: string } | null>(null);
  const [fallbackLines, setFallbackLines] = useState<RequestFormValues["lines"] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  async function create(values: RequestFormValues): Promise<RequestDetail> {
    const body: Record<string, unknown> = toPayload(values);
    if (reply?.ai_draft) body.ai_draft = reply.ai_draft;
    if (source) {
      body.source_channel = source.channel;
      body.source_message = source.text;
    }
    return post<RequestDetail>("/requests", body);
  }

  const prefill: RequestFormValues | undefined = reply?.draft ? {
    category_id: reply.draft.category_id, title: reply.draft.title, justification: reply.draft.justification,
    cost_center: reply.draft.cost_center, needed_by: reply.draft.needed_by, suggested_vendor_id: null,
    lines: reply.draft.lines.map((l) => ({ description: l.description, qty: l.qty, unit: "",
                                           est_rate: needFirst ? "" : l.est_rate ?? "" })),
  } : fallbackLines ? {
    category_id: "", title: fallbackLines[0]?.description ?? "", justification: "", cost_center: "", needed_by: null,
    suggested_vendor_id: null, lines: fallbackLines,
  } : undefined;

  function switchMode(next: string) {
    setMode(next === "message" ? "message" : "form");
    setReply(null);
    setSource(null);
    setFallbackLines(null);
    setNotice(null);
    setVersion((n) => n + 1);
  }

  function onMessageRead(channel: Channel, text: string, draft: DraftReply | null) {
    setSource({ channel, text });
    setReply(draft);
    if (draft) {
      setFallbackLines(null);
      setNotice(null);
    } else {
      const lines = readMessage(text);
      setFallbackLines(lines.length ? lines : [{ description: "", qty: "1", unit: "", est_rate: "" }]);
      setNotice(lines.length
        ? `Read ${lines.length} item${lines.length === 1 ? "" : "s"} from the message. Check them, then choose what kind of thing it is.`
        : "Couldn't read the items from the message. Copy them into the form below; the message stays beside it.");
    }
    setVersion((v) => v + 1);
  }

  async function save(values: RequestFormValues, submit: boolean) {
    const created = await create(values);
    const forSomeoneElse = values.requested_for_id && values.requested_for_id !== me.id;
    if (submit && !forSomeoneElse) await post(`/requests/${created.id}/submit`);
    router.push(`/requests/${created.id}`);
  }

  return (
    <>
      <PageHeader
        title={needFirst ? "Raise a need" : "New request"}
        description={needFirst
          ? "Say what you need and how many. Your manager approves it, then procurement orders it from the right vendor."
          : "Describe what you need. Your category's buyer takes it from there."}
      />
      <div className="flex flex-col gap-6">
        {needFirst ? (
          <Tabs value={mode} onValueChange={switchMode} tabs={[
            { value: "form", label: "Fill the form", content: null },
            { value: "message", label: "Paste a WhatsApp / email message", content: null },
          ]} />
        ) : null}
        {mode === "message" ? <MessageIntake onRead={onMessageRead} /> : <IntakeAgent onDraft={(r) => { setReply(r); setVersion((v) => v + 1); }} />}
        {source ? <OriginalMessage channel={source.channel} text={source.text} /> : null}
        {notice ? <p role="status" className="rounded-lg border border-border bg-ice px-3 py-2 text-sm text-heading">{notice}</p> : null}
        {reply ? <DraftSummary reply={reply} needFirst={needFirst} /> : null}
        {mode === "message" && !source ? null : (
          <RequestForm
            key={version}
            prefill={prefill}
            needFirst={needFirst}
            canRaiseForOthers={canRaiseForOthers}
            submitLabel={needFirst ? "Send to my manager" : "Submit request"}
            onSave={(values) => save(values, true)}
            secondaryLabel="Save as draft"
            onSecondary={(values) => save(values, false)}
          />
        )}
      </div>
    </>
  );
}
