"use client";

/**
 * Logged-in shell (PROMPTS Step 3): navy sidebar with navigation, the user's name and role,
 * and sign-out. Every page inside (app)/ gets the session through useMe().
 */
import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, FileText, Inbox, ListChecks, LogOut, Package, ScrollText, ShieldCheck } from "lucide-react";

import { SessionProvider, useMe } from "@/components/session";
import { post } from "@/lib/api";
import { formatINR, ROLE_LABELS } from "@/lib/format";

const NAV = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/requests", label: "Requests", icon: ListChecks },
  { href: "/invoices", label: "Invoices", icon: FileText },
  { href: "/pos", label: "POs", icon: Package },
  { href: "/vendors", label: "Vendors", icon: Building2 },
  { href: "/audit", label: "Audit", icon: ScrollText },
];

function Shell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();

  async function signOut() {
    await post("/auth/logout").catch(() => undefined);
    // A full page load on purpose, so no cached screen of the signed-out user survives.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }

  return (
    <div className="flex min-h-screen flex-1">
      <aside className="flex w-60 shrink-0 flex-col bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2 px-5">
          <ShieldCheck className="size-5 text-cyan" aria-hidden />
          <span className="font-semibold tracking-tight">Orrfin</span>
        </div>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-3 py-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link key={href} href={href} aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                      active ? "bg-sidebar-accent font-medium text-white shadow-[inset_3px_0_0_var(--orffin-cyan)]"
                             : "text-white/75 hover:bg-sidebar-accent hover:text-white"}`}>
                <Icon className={`size-4 ${active ? "text-cyan" : ""}`} aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-sidebar-border px-4 py-4">
          <p className="truncate text-sm font-medium">{me.full_name}</p>
          <p className="text-xs text-cyan">
            {ROLE_LABELS[me.role]}
            {Number(me.approval_limit) > 0 ? ` · limit ${formatINR(me.approval_limit)}` : ""}
          </p>
          <button type="button" onClick={signOut}
                  className="mt-3 flex items-center gap-2 text-xs text-white/75 hover:text-white">
            <LogOut className="size-3.5" aria-hidden /> Sign out
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-8">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
