/**
 * The frame for pages seen before sign-in: sign in, accept a team invitation, and the supplier
 * portal's sign-in and set-password pages (Step 41).
 * Navy brand panel on the left saying plainly what Orrfin does; the form on white on the right.
 * Below `lg` only the form shows, with the mark above it.
 */
import type { ReactNode } from "react";
import { CircleCheck, ShieldCheck } from "lucide-react";

const POINTS = [
  "Requests reach the right approver, in order, within their limit.",
  "Every invoice is matched to its PO and receipt before anyone pays it.",
  "A named person decides each exception, and the audit trail records who.",
];

export function AuthLayout({ children, headline = "Every purchase checked before it's paid.", points = POINTS }: {
  children: ReactNode;
  headline?: string;
  points?: string[];
}) {
  return (
    <div className="grid min-h-screen flex-1 lg:grid-cols-[minmax(420px,5fr)_7fr]">
      <aside className="hidden flex-col justify-between bg-navy px-12 py-10 text-white lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-blue-dark ring-1 ring-white/10">
            <ShieldCheck className="size-5 text-cyan" aria-hidden />
          </span>
          <span className="text-xl font-semibold tracking-tight">Orrfin</span>
        </div>
        <div className="max-w-md">
          <p className="font-display text-[2.6rem] leading-[1.1]">{headline}</p>
          <ul className="mt-8 space-y-4">
            {points.map((point) => (
              <li key={point} className="flex gap-3 text-[15px] leading-relaxed text-white/75">
                <CircleCheck className="mt-0.5 size-5 shrink-0 text-cyan" aria-hidden />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-white/45">Controlled prototype on synthetic data. Draft-only ERP writes, simulated payments.</p>
      </aside>
      <main className="flex items-center justify-center bg-ice-light px-4 py-12 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex size-9 items-center justify-center rounded-lg bg-navy">
              <ShieldCheck className="size-5 text-cyan" aria-hidden />
            </span>
            <span className="text-xl font-semibold tracking-tight text-heading">Orrfin</span>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
