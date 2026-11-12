"use client";

/**
 * The logged-in app shell (BUILD_PLAN v3.0 change 37).
 *
 *   rail (product areas) | side panel (pages of the open area) | top bar + page
 *
 * The rail answers "which part of the product", the panel "which page", and the top bar holds
 * what follows a person everywhere: where they are, jump-to search, their open tasks, Ask Orrfin
 * and their own name and role. Below the `lg` width the rail and panel become a slide-in drawer.
 */
import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronRight, LogOut, Menu, Search, ShieldCheck, Sparkles, X } from "lucide-react";

import { AssistantPanel } from "@/components/assistant-panel";
import { CommandPalette } from "@/components/shell/command-palette";
import { useMe } from "@/components/session";
import { post } from "@/lib/api";
import { formatINR, ROLE_LABELS } from "@/lib/format";
import { locate, navigationFor, type NavArea } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

interface TaskCounts {
  total: number;
  overdue: number;
}

function TaskCountPill({ counts, onDark }: { counts: TaskCounts; onDark: boolean }) {
  if (!counts.total) return null;
  const label = `${counts.total} open tasks${counts.overdue ? `, ${counts.overdue} overdue` : ""}`;
  // Overdue is said in the label as well as shown in red: colour alone never carries status (BRAND.md).
  const colour = counts.overdue ? "bg-error text-white" : onDark ? "bg-cyan text-navy" : "bg-primary text-white";
  return (
    <span aria-label={label} className={`ml-auto rounded-full px-1.5 text-[11px] font-semibold leading-5 tabular-nums ${colour}`}>
      {counts.total}
    </span>
  );
}

function Rail({ areas, openKey }: { areas: NavArea[]; openKey: string | undefined }) {
  return (
    <nav aria-label="Product areas" className="flex w-[76px] shrink-0 flex-col items-center gap-1 bg-navy py-3">
      <Link href="/home" aria-label="Orrfin home" className="mb-3 flex size-10 items-center justify-center rounded-xl bg-blue-dark">
        <ShieldCheck className="size-5 text-cyan" aria-hidden />
      </Link>
      {areas.map((area) => {
        const open = area.key === openKey;
        const Icon = area.icon;
        return (
          <Link key={area.key} href={area.items[0].href} aria-current={open ? "true" : undefined}
                className={`flex w-16 flex-col items-center gap-1 rounded-lg py-2 text-[11px] font-medium transition-colors ${
                  open ? "bg-blue-dark text-white shadow-[inset_3px_0_0_var(--orffin-cyan)]"
                       : "text-white/65 hover:bg-blue-dark/60 hover:text-white"}`}>
            <Icon className={`size-[18px] ${open ? "text-cyan" : ""}`} aria-hidden />
            {area.label}
          </Link>
        );
      })}
    </nav>
  );
}

function SidePanel({ area, activeHref, counts, onNavigate }: {
  area: NavArea;
  activeHref: string | undefined;
  counts: TaskCounts;
  onNavigate?: () => void;
}) {
  return (
    <nav aria-label={`${area.label} pages`} className="flex w-56 shrink-0 flex-col bg-navy-soft px-3 py-4 text-white">
      <div className="px-2 pb-4">
        <p className="font-display text-xl leading-tight">{area.label}</p>
        <p className="mt-1 text-xs leading-snug text-white/60">{area.summary}</p>
      </div>
      <ul className="flex flex-col gap-0.5">
        {area.items.map((item) => {
          const active = item.href === activeHref;
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link href={item.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                      active ? "bg-blue-dark font-medium text-white" : "text-white/75 hover:bg-blue-dark/60 hover:text-white"}`}>
                <Icon className={`size-4 shrink-0 ${active ? "text-cyan" : ""}`} aria-hidden />
                <span className="min-w-0 truncate">{item.label}</span>
                {item.showsTaskCount ? <TaskCountPill counts={counts} onDark /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const areas = navigationFor(me.role);
  const here = locate(areas, pathname);
  // A page outside the map (the Control Graph, opened from a record) keeps the Home area open.
  const openArea = here?.area ?? areas[0];

  // Re-read on every navigation, so the count follows actions taken on the pages.
  const { data: tasks } = useApi<{ overdue: boolean }[]>(`/tasks?at=${encodeURIComponent(pathname)}`);
  const counts: TaskCounts = { total: tasks?.length ?? 0, overdue: tasks?.filter((t) => t.overdue).length ?? 0 };

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function signOut() {
    await post("/auth/logout").catch(() => undefined);
    // A full page load on purpose, so no cached screen of the signed-out user survives.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }

  return (
    <div className="flex min-h-screen flex-1">
      <div className="sticky top-0 hidden h-screen lg:flex">
        <Rail areas={areas} openKey={openArea.key} />
        <SidePanel area={openArea} activeHref={here?.item.href} counts={counts} />
      </div>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 flex bg-navy/45 lg:hidden" onClick={() => setDrawerOpen(false)}>
          <div className="flex h-full" onClick={(event) => event.stopPropagation()}>
            <Rail areas={areas} openKey={openArea.key} />
            <SidePanel area={openArea} activeHref={here?.item.href} counts={counts} onNavigate={() => setDrawerOpen(false)} />
          </div>
          <button type="button" aria-label="Close menu" className="m-3 self-start rounded-lg bg-white p-2 text-heading">
            <X className="size-4" aria-hidden />
          </button>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-white/90 px-4 backdrop-blur sm:px-6">
          <button type="button" aria-label="Open menu" onClick={() => setDrawerOpen(true)}
                  className="rounded-lg p-2 text-heading hover:bg-ice lg:hidden">
            <Menu className="size-5" aria-hidden />
          </button>

          <nav aria-label="You are here" className="hidden min-w-0 items-center gap-1.5 text-sm sm:flex">
            <span className="text-muted-foreground">{openArea.label}</span>
            {here ? (
              <>
                <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden />
                <span className="truncate font-medium text-heading">{here.item.label}</span>
              </>
            ) : null}
          </nav>

          <button type="button" onClick={() => setPaletteOpen(true)}
                  className="ml-auto flex h-9 w-full max-w-64 items-center gap-2 rounded-lg border border-border bg-ice-light px-3 text-sm text-muted-foreground hover:border-primary/50">
            <Search className="size-4 shrink-0" aria-hidden />
            <span className="flex-1 truncate text-left">Jump to a page</span>
            <kbd className="hidden rounded border border-border bg-white px-1.5 text-[11px] font-medium sm:inline">Ctrl K</kbd>
          </button>

          <Link href="/tasks" aria-label={`My tasks: ${counts.total} open${counts.overdue ? `, ${counts.overdue} overdue` : ""}`}
                className="relative rounded-lg p-2 text-heading hover:bg-ice">
            <Bell className="size-5" aria-hidden />
            {counts.total ? (
              <span aria-hidden className={`absolute right-0.5 top-0.5 min-w-4 rounded-full px-1 text-center text-[10px] font-semibold leading-4 text-white ${counts.overdue ? "bg-error" : "bg-primary"}`}>
                {counts.total}
              </span>
            ) : null}
          </Link>

          <button type="button" onClick={() => setAssistantOpen(true)}
                  className="flex h-9 shrink-0 items-center gap-2 rounded-lg bg-navy px-3 text-sm font-medium text-white hover:bg-blue-dark">
            <Sparkles className="size-4 text-cyan" aria-hidden />
            <span className="hidden sm:inline">Ask Orrfin</span>
          </button>

          <div className="hidden shrink-0 items-center gap-3 border-l border-border pl-4 md:flex">
            <div className="text-right leading-tight">
              <p className="max-w-40 truncate text-sm font-medium text-heading">{me.full_name}</p>
              <p className="text-xs text-muted-foreground">
                {ROLE_LABELS[me.role]}
                {Number(me.approval_limit) > 0 ? `, approves up to ${formatINR(me.approval_limit)}` : ""}
              </p>
            </div>
          </div>
          <button type="button" onClick={signOut} aria-label="Sign out" title="Sign out"
                  className="rounded-lg p-2 text-muted-foreground hover:bg-ice hover:text-heading">
            <LogOut className="size-4" aria-hidden />
          </button>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>

      {assistantOpen ? <AssistantPanel onClose={() => setAssistantOpen(false)} /> : null}
      {paletteOpen ? <CommandPalette areas={areas} onClose={() => setPaletteOpen(false)} /> : null}
    </div>
  );
}
