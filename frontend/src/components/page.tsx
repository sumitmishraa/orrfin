/**
 * Page scaffolding shared by the logged-in screens: title row, notices, empty states, panels and the
 * table classes for small inline tables. Step 41 restyled these for the GoHighLevel-style shell: one
 * sans typeface, white cards on the ice workspace, light table headers. Lists use DataTable
 * (components/ui/data-table.tsx); these classes remain for short tables inside a panel.
 */
import type { ReactNode } from "react";
import { CircleAlert, LoaderCircle } from "lucide-react";

export function PageHeader({ title, description, actions, meta }: {
  title: string;
  description?: string;
  actions?: ReactNode;
  /** A small line above the title, e.g. a back link or the record's reference. */
  meta?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0">
        {meta ? <div className="mb-1.5 text-sm text-muted-foreground">{meta}</div> : null}
        <h1 className="text-[1.375rem] font-semibold leading-tight tracking-tight text-heading sm:text-2xl">{title}</h1>
        {description ? <p className="mt-1.5 max-w-[72ch] text-sm leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function ErrorNotice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg border border-error/30 bg-error/5 px-3 py-2 text-sm text-error">
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      {message}
    </p>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      {label}
    </p>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-white px-6 py-12 text-center text-sm leading-relaxed text-muted-foreground">
      {children}
    </div>
  );
}

export function Panel({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-white shadow-raised">
      {title ? (
        <div className="flex min-h-12 items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="text-[15px] font-semibold text-heading">{title}</h2>
          {actions}
        </div>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Classes for a short table inside a panel: light header, hairline rows, right-aligned numbers via `num`. */
export const table = {
  wrap: "overflow-x-auto rounded-xl border border-border bg-white shadow-raised",
  table: "w-full text-sm",
  th: "whitespace-nowrap border-b border-border bg-ice-light px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground",
  td: "border-t border-border/70 px-3 py-3 align-top",
  num: "text-right tabular-nums",
};
