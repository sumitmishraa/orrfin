/**
 * Page scaffolding shared by the logged-in screens: title row, notices, empty states, tables.
 */
import type { ReactNode } from "react";
import { CircleAlert, LoaderCircle } from "lucide-react";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-heading">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
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
    <div className="rounded-xl border border-dashed border-border bg-white px-6 py-10 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

export function Panel({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-white">
      {title ? (
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-heading">{title}</h2>
          {actions}
        </div>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Table classes: ice header, thin borders, right-aligned numbers via `num`. */
export const table = {
  wrap: "overflow-x-auto rounded-xl border border-border bg-white",
  table: "w-full text-sm",
  th: "bg-ice px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-heading",
  td: "border-t border-border px-3 py-2 align-top",
  num: "text-right tabular-nums",
};
