"use client";

/**
 * Orrfin Assistant side panel (BUILD_PLAN v2.3 change 25; ADR 0007; PROMPTS Step 23).
 * The assistant reads, explains and drafts; it never acts. Answers are AI-written, link only to
 * records Orrfin returned, and carry a warning when a ₹ figure could not be found in the records.
 * The conversation lives only in this panel (the server logs each question for audit).
 */
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LoaderCircle, Send, Sparkles, TriangleAlert, X } from "lucide-react";

import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";

interface Reply {
  available: boolean;
  message?: string;
  answer?: string;
  links?: { type: string; label: string; href: string }[];
  grounded?: boolean;
  warning?: string | null;
  tools_used?: string[];
}

interface Message { role: "user" | "assistant"; text: string; reply?: Reply }

function pageContext(pathname: string): { type: "request" | "invoice"; id: string } | null {
  const match = pathname.match(/^\/(requests|invoices)\/([0-9a-f-]{36})/);
  return match ? { type: match[1] === "requests" ? "request" : "invoice", id: match[2] } : null;
}

function suggestions(role: string, context: ReturnType<typeof pageContext>): string[] {
  if (context?.type === "invoice") return ["Why is this invoice on hold?", "Who can approve this invoice, and what is left?"];
  if (context?.type === "request") return ["Where is this request stuck?", "What will this do to the budget?"];
  const common = ["What is waiting on me?"];
  if (role === "requester") return [...common, "Where are my requests?", "What are the approval rules?"];
  if (role === "finance" || role === "admin") return [...common, "Which invoices are on hold, and how much is at risk?", "Which approvals are overdue?"];
  return [...common, "Which approvals are overdue?", "How much have we spent this quarter by category?"];
}

export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const me = useMe();
  const pathname = usePathname();
  const context = pageContext(pathname);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    const history = messages.map((m) => ({ role: m.role, text: m.role === "user" ? m.text : m.reply?.answer ?? m.text }));
    setMessages((list) => [...list, { role: "user", text: question }]);
    setDraft("");
    try {
      const reply = await post<Reply>("/assistant/ask", { question, history, context });
      setMessages((list) => [...list, { role: "assistant", text: reply.answer ?? reply.message ?? "", reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not ask.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside role="dialog" aria-label="Orrfin Assistant"
           className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-white shadow-2xl">
      <header className="flex items-center justify-between border-b border-border bg-navy px-4 py-3 text-white">
        <span className="flex items-center gap-2 font-semibold"><Sparkles className="size-4 text-cyan" aria-hidden /> Ask Orrfin</span>
        <button type="button" aria-label="Close assistant" onClick={onClose}><X className="size-4" /></button>
      </header>
      <p className="border-b border-border bg-ice px-4 py-2 text-xs text-heading">
        Reads your records with your permissions and explains them. It cannot approve, pay or change anything.
      </p>
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4" aria-live="polite">
        {messages.length === 0 ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-muted-foreground">Try:</p>
            {suggestions(me.role, context).map((s) => (
              <button key={s} type="button" onClick={() => void ask(s)}
                      className="rounded-lg border border-border px-3 py-2 text-left text-sm text-heading hover:bg-ice">{s}</button>
            ))}
          </div>
        ) : null}
        {messages.map((m, i) => m.role === "user" ? (
          <p key={i} className="self-end rounded-lg rounded-br-none bg-navy px-3 py-2 text-sm text-white">{m.text}</p>
        ) : (
          <div key={i} className="flex flex-col gap-2 rounded-lg rounded-bl-none border border-border px-3 py-2 text-sm">
            {m.reply && !m.reply.available ? (
              <p className="text-muted-foreground">{m.reply.message}</p>
            ) : (
              <>
                <p className="whitespace-pre-wrap">{m.text}</p>
                {m.reply?.warning ? (
                  <p className="flex items-start gap-1.5 rounded bg-warning/10 px-2 py-1 text-xs text-warning">
                    <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {m.reply.warning}
                  </p>
                ) : null}
                {m.reply?.links?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {m.reply.links.map((l) => (
                      <Link key={l.href + l.label} href={l.href} className="rounded bg-ice px-2 py-0.5 text-xs font-medium text-primary hover:underline">{l.label}</Link>
                    ))}
                  </div>
                ) : null}
                <p className="text-[11px] text-muted-foreground">AI-written · check the linked page{m.reply?.tools_used?.length ? ` · looked at: ${m.reply.tools_used.join(", ").replaceAll("_", " ")}` : ""}</p>
              </>
            )}
          </div>
        ))}
        {busy ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" aria-hidden /> Looking it up…</p> : null}
        {error ? <p role="alert" className="text-sm text-error">{error}</p> : null}
      </div>
      <form className="flex items-end gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); void ask(draft); }}>
        <Textarea aria-label="Your question" rows={2} value={draft} maxLength={2000} placeholder="Ask about a request, invoice, budget or rule"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(draft); } }} />
        <Button type="submit" size="icon" aria-label="Ask" disabled={busy || !draft.trim()}><Send aria-hidden /></Button>
      </form>
    </aside>
  );
}
