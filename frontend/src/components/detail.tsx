/**
 * The layout every record page uses (Step 41, Conceptzilla-style): a back link above the title, the
 * work on the left (lines, decisions, history), and a right-hand column with the record's key facts
 * and the people on it. Below `lg` the right column moves above the work, so the facts come first.
 */
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-heading">
      <ArrowLeft className="size-4" aria-hidden /> {label}
    </Link>
  );
}

export function DetailLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="order-2 flex min-w-0 flex-col gap-6 lg:order-1">{main}</div>
      <aside className="order-1 flex flex-col gap-4 lg:sticky lg:top-32 lg:order-2">{aside}</aside>
    </div>
  );
}

/** A titled card in the right-hand column. */
export function AsideCard({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-white shadow-raised">
      <div className="flex items-center justify-between gap-2 px-4 pt-3.5">
        <h2 className="text-[15px] font-semibold text-heading">{title}</h2>
        {actions}
      </div>
      <div className="px-4 pb-3 pt-1">{children}</div>
    </section>
  );
}

export interface ChainStep {
  key: string | number;
  label: string;
  /** Who decided, or who it waits for. */
  person?: string | null;
  state: "done" | "current" | "waiting" | "stopped";
  note?: string;
}

/** A vertical stepper for an approval chain or any ordered checks: done, current, waiting, stopped. */
export function Chain({ steps }: { steps: ChainStep[] }) {
  const dot: Record<ChainStep["state"], string> = {
    done: "bg-success border-success",
    current: "bg-white border-warning ring-3 ring-warning/20",
    waiting: "bg-white border-border",
    stopped: "bg-error border-error",
  };
  const word: Record<ChainStep["state"], string> = { done: "Done", current: "Waiting now", waiting: "Not yet", stopped: "Stopped" };
  return (
    <ol className="relative mt-1 space-y-4 border-l border-border pl-5">
      {steps.map((s) => (
        <li key={s.key} className="relative">
          <span aria-hidden className={`absolute -left-[26.5px] top-1 size-3 rounded-full border-2 ${dot[s.state]}`} />
          <p className="text-sm font-medium text-heading">{s.label}</p>
          <p className="text-xs text-muted-foreground">
            {s.person ? <><span className="sr-only">{word[s.state]}. </span>{s.person}</> : word[s.state]}
            {s.note ? ` · ${s.note}` : ""}
          </p>
        </li>
      ))}
    </ol>
  );
}
