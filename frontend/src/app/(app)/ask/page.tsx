"use client";

/**
 * Ask Orrfin: chat with a superagent (BUILD_PLAN change 47, ADR 0007).
 *
 * The agent reads only what you could see on the pages, and can only *propose*: a request, an RFQ,
 * a supplier invitation or a workflow draft appears as a card. Nothing exists until you press
 * Submit, and the server then runs the same checks as the normal page.
 */
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Send, Sparkles } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import { useApi } from "@/lib/use-api";

interface Card { id: string; kind: string; payload: Record<string, unknown>; expires_at: string }
interface Reply { available: boolean; message?: string; answer?: string; warning?: string | null; proposals?: Card[]; links?: { label: string; href: string }[] }
interface Message { role: "user" | "assistant"; text: string; cards?: Card[]; links?: Reply["links"]; warning?: string | null }

const KIND_TITLE: Record<string, string> = { request: "Draft purchase request", rfq: "Draft RFQ", supplier_invite: "Supplier invitation", workflow_draft: "Workflow draft" };

function ProposalCard({ card }: { card: Card }) {
  const [done, setDone] = useState<{ href: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="rounded-lg border border-primary/30 bg-ice p-3 text-sm">
      <p className="font-medium text-heading">{KIND_TITLE[card.kind] ?? card.kind}</p>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(card.payload, null, 2)}</pre>
      <ErrorNotice message={error} />
      {done ? <Link href={done.href} className="font-medium text-primary underline">Created. Open it</Link> : (
        <Button size="sm" className="mt-2" onClick={async () => {
          try { setDone(await post<{ href: string }>(`/agents/proposals/${card.id}/submit`)); } catch (e) { setError(e instanceof Error ? e.message : "Could not submit."); }
        }}>Check and submit</Button>
      )}
      <p className="mt-1 text-xs text-muted-foreground">Proposed by AI. Nothing is created until you submit; the usual checks and approvals still apply.</p>
    </div>
  );
}

export default function AskPage() {
  const agents = useApi<Record<string, { title: string; summary: string }>>("/agents");
  const [agent, setAgent] = useState("concierge");
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);

  if (agents.loading) return <Loading />;

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const history = messages.map((m) => ({ role: m.role, text: m.text }));
    setMessages((m) => [...m, { role: "user", text }]);
    setText("");
    setBusy(true);
    try {
      const reply = await post<Reply>(`/agents/${agent}/ask`, { question: text, history: history.slice(-8) });
      setMessages((m) => [...m, reply.available
        ? { role: "assistant", text: reply.answer ?? "", cards: reply.proposals, links: reply.links, warning: reply.warning }
        : { role: "assistant", text: reply.message ?? "The assistant is unavailable." }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", text: err instanceof Error ? err.message : "Something went wrong." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Ask Orrfin" description="Ask a question or describe what you need. Agents read what you can see and propose; you decide." />
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-primary" aria-hidden />
        <Select aria-label="Agent" value={agent} onChange={(e) => { setAgent(e.target.value); setMessages([]); }}>
          {Object.entries(agents.data ?? {}).map(([key, a]) => <option key={key} value={key}>{a.title}</option>)}
        </Select>
        <span className="text-sm text-muted-foreground">{agents.data?.[agent]?.summary}</span>
      </div>
      <Panel>
        <div className="space-y-4 p-4" aria-live="polite">
          {messages.length === 0 ? <p className="text-sm text-muted-foreground">Try: “Draft a request for two 27-inch monitors for the new analysts”.</p> : null}
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "ml-auto max-w-[80%] rounded-lg bg-primary/10 p-3 text-sm" : "max-w-[90%] space-y-2 text-sm"}>
              <p className="whitespace-pre-wrap">{m.text}</p>
              {m.warning ? <p className="text-xs text-warning">{m.warning}</p> : null}
              {m.links?.map((l) => <Link key={l.href} href={l.href} className="mr-3 text-primary underline">{l.label}</Link>)}
              {m.cards?.map((c) => <ProposalCard key={c.id} card={c} />)}
            </div>
          ))}
          {busy ? <Loading label="Thinking…" /> : null}
        </div>
        <form onSubmit={send} className="flex gap-2 border-t border-border p-3">
          <Textarea aria-label="Your message" className="min-h-12 flex-1" maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" disabled={busy || !text.trim()}><Send aria-hidden /> Send</Button>
        </form>
      </Panel>
    </div>
  );
}
