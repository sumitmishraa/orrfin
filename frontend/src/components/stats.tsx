/**
 * Dashboard building blocks (BUILD_PLAN v2.3 change 23): number tiles and horizontal bar lists.
 * Plain HTML, no chart package. Amounts are always printed from the API's exact decimal string;
 * Number() is used only to size a bar, where a rounding error cannot mislead anyone.
 */
import type { ReactNode } from "react";

type Tone = "default" | "good" | "warn" | "bad";

const TONE_TEXT: Record<Tone, string> = {
  default: "text-heading",
  good: "text-success",
  warn: "text-warning",
  bad: "text-error",
};

export function StatTile({ label, value, sub, tone = "default" }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-xl border border-border bg-white px-4 py-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`break-words text-xl font-semibold tabular-nums sm:text-2xl ${TONE_TEXT[tone]}`}>{value}</span>
      {sub ? <span className="text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

export interface BarRow {
  label: string;
  /** Exact value as sent by the API (money or a count), used for the bar length. */
  value: string | number;
  /** What to print, e.g. a formatted rupee amount. */
  display: string;
}

export function BarList({ rows, empty, color = "bg-brand-blue" }: { rows: BarRow[]; empty: string; color?: string }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  const max = Math.max(...rows.map((r) => Number(r.value)), 0);
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((row) => {
        const pct = max > 0 ? Math.max(2, (Number(row.value) / max) * 100) : 0;
        return (
          <li key={row.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{row.label}</span>
              <span className="shrink-0 font-medium tabular-nums">{row.display}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ice" aria-hidden>
              <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
