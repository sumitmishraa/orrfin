/**
 * Small display pieces shared by every screen (Step 41 design kit, docs/BRAND.md):
 * Avatar and AvatarGroup (initials, colour fixed per name), StatusPill (icon + text, never colour
 * alone), Kbd, Skeleton, and MetaList (the "label · value" rows in detail panels).
 */
import type { ComponentType, ReactNode } from "react";
import { cn } from "cn";

/* --- Avatar -------------------------------------------------------------------------------------- */

const AVATAR_TONES = 8;

/** Same name, same colour, on every screen and every visit. */
function toneFor(name: string): number {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return (hash % AVATAR_TONES) + 1;
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const first = words[0][0] ?? "";
  const last = words.length > 1 ? words[words.length - 1][0] ?? "" : "";
  return (first + last).toUpperCase();
}

const AVATAR_SIZES = { xs: "size-6 text-[10px]", sm: "size-8 text-xs", md: "size-9 text-[13px]", lg: "size-12 text-base" };

export function Avatar({ name, size = "sm", className }: { name: string; size?: keyof typeof AVATAR_SIZES; className?: string }) {
  const tone = toneFor(name);
  return (
    <span
      aria-hidden
      className={cn("inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold", AVATAR_SIZES[size], className)}
      style={{ background: `var(--orffin-avatar-${tone}-bg)`, color: `var(--orffin-avatar-${tone}-fg)` }}
    >
      {initials(name)}
    </span>
  );
}

export function AvatarGroup({ names, max = 4 }: { names: string[]; max?: number }) {
  const shown = names.slice(0, max);
  const rest = names.length - shown.length;
  return (
    <span className="flex items-center -space-x-1.5" aria-label={names.join(", ")}>
      {shown.map((name) => <Avatar key={name} name={name} size="xs" className="ring-2 ring-white" />)}
      {rest > 0 ? (
        <span className="inline-flex size-6 items-center justify-center rounded-full bg-ice text-[10px] font-semibold text-heading ring-2 ring-white">
          +{rest}
        </span>
      ) : null}
    </span>
  );
}

/** Avatar, name and a muted second line: the "who" cell of every people table. */
export function PersonCell({ name, detail, size = "sm" }: { name: string; detail?: ReactNode; size?: keyof typeof AVATAR_SIZES }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <Avatar name={name} size={size} />
      <span className="min-w-0 leading-tight">
        <span className="block truncate font-medium text-foreground">{name}</span>
        {detail ? <span className="block truncate text-xs text-muted-foreground">{detail}</span> : null}
      </span>
    </span>
  );
}

/* --- Status pill --------------------------------------------------------------------------------- */

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

const TONES: Record<Tone, string> = {
  neutral: "border-border bg-white text-heading",
  info: "border-brand-bright/30 bg-ice text-heading",
  // BRAND.md: success is the brand blue (#2b64ae), always with its check icon.
  success: "border-success/25 bg-success/8 text-success",
  warning: "border-warning/35 bg-warning/10 text-[#8a5a12]",
  danger: "border-error/30 bg-error/8 text-error",
  muted: "border-transparent bg-muted text-muted-foreground",
};

export function StatusPill({ tone = "neutral", icon: Icon, children, className }: {
  tone?: Tone;
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium leading-4", TONES[tone], className)}>
      {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden /> : null}
      {children}
    </span>
  );
}

/* --- Kbd, Skeleton ------------------------------------------------------------------------------- */

export function Kbd({ children, onDark = false }: { children: ReactNode; onDark?: boolean }) {
  return (
    <kbd className={cn("inline-flex h-5 items-center rounded border px-1.5 font-sans text-[11px] font-medium",
      onDark ? "border-white/15 bg-white/5 text-white/60" : "border-border bg-white text-muted-foreground")}>
      {children}
    </kbd>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block animate-pulse rounded-md bg-ice", className)} />;
}

/* --- MetaList ------------------------------------------------------------------------------------ */

export interface MetaRow {
  label: string;
  value: ReactNode;
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
}

/** Label on the left, value on the right, a hairline between rows (detail panels, Conceptzilla style). */
export function MetaList({ rows, className }: { rows: MetaRow[]; className?: string }) {
  return (
    <dl className={cn("divide-y divide-border/70", className)}>
      {rows.map(({ label, value, icon: Icon }) => (
        <div key={label} className="flex items-center justify-between gap-4 py-2.5 text-sm">
          <dt className="flex items-center gap-2 text-muted-foreground">
            {Icon ? <Icon className="size-4 shrink-0" aria-hidden /> : null}
            {label}
          </dt>
          <dd className="min-w-0 truncate text-right font-medium text-foreground">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A small uppercase section label, used in panels and the sidebar. */
export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground", className)}>{children}</p>;
}
