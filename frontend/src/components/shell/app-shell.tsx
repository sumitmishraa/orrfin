"use client";

/**
 * The logged-in app shell (BUILD_PLAN v3.0 change 37, redesigned in Step 41, GoHighLevel style).
 *
 *   navy sidebar                         | header: area title · area tabs · Ask Orrfin · tasks
 *   ─ Orrfin mark, collapse              |
 *   ─ workspace card (org, plan, menu)   | page
 *   ─ search (Ctrl K) · New request      |
 *   ─ sections → product areas           |
 *   ─ Settings · the signed-in person    |
 *
 * An area is one sidebar entry; its pages are the tabs across the top. The sidebar collapses to an
 * icon strip (remembered on this browser only). Below `lg` it becomes a slide-in drawer.
 */
import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell, Building2, ChevronsUpDown, FilePlus2, FileText, ListTodo, LogOut, Menu, PanelLeftClose, PanelLeftOpen,
  Search, ShieldCheck, Sparkles, UserCog, UserPlus, Users, X,
} from "lucide-react";
import { cn } from "cn";

import { AssistantPanel } from "@/components/assistant-panel";
import { CommandPalette, type QuickAction } from "@/components/shell/command-palette";
import { useMe } from "@/components/session";
import { DropdownMenu, LinkTabs, type MenuAction } from "@/components/ui/controls";
import { Avatar, Kbd } from "@/components/ui/display";
import { post } from "@/lib/api";
import { formatINR, ROLE_LABELS } from "@/lib/format";
import { locate, NAV_SECTIONS, navigationFor, type NavArea } from "@/lib/navigation";
import type { Me } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const COLLAPSE_KEY = "orrfin.sidebar.collapsed";

interface TaskCounts {
  total: number;
  overdue: number;
}

function CountPill({ counts }: { counts: TaskCounts }) {
  if (!counts.total) return null;
  // Overdue is said in the label as well as shown in red: colour alone never carries status (BRAND.md).
  return (
    <span aria-label={`${counts.total} open${counts.overdue ? `, ${counts.overdue} overdue` : ""}`}
          className={cn("ml-auto rounded-full px-1.5 text-[11px] font-semibold leading-5 tabular-nums",
            counts.overdue ? "bg-error text-white" : "bg-cyan text-navy")}>
      {counts.total}
    </span>
  );
}

async function signOut() {
  await post("/auth/logout").catch(() => undefined);
  // A full page load on purpose, so no cached screen of the signed-out user survives.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = "/login";
}

function accountMenu(me: Me): MenuAction[] {
  const items: MenuAction[] = [{ label: "Profile & security", icon: UserCog, href: "/settings" }];
  if (me.role === "admin") items.push({ label: "Team & roles", icon: Users, href: "/settings/team" });
  if (me.role === "admin" || me.role === "finance") items.push({ label: "Legal entities", icon: Building2, href: "/settings/entities" });
  items.push({ label: "Sign out", icon: LogOut, onSelect: signOut, separated: true });
  return items;
}

function SidebarLink({ href, icon: Icon, label, active, collapsed, onNavigate, trailing }: {
  href: string;
  icon: NavArea["icon"];
  label: string;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
  trailing?: ReactNode;
}) {
  return (
    <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} title={collapsed ? label : undefined}
          className={cn("group relative flex h-9 items-center gap-3 rounded-lg text-[13.5px] transition-colors",
            collapsed ? "justify-center px-0" : "px-2.5",
            active ? "bg-sidebar-active font-medium text-white" : "text-sidebar-text hover:bg-sidebar-hover hover:text-white")}>
      {active ? <span aria-hidden className="absolute -left-3 top-1.5 bottom-1.5 w-[3px] rounded-r bg-cyan" /> : null}
      <Icon className={cn("size-[18px] shrink-0", active ? "text-cyan" : "text-white/55 group-hover:text-white/80")} aria-hidden />
      {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
      {collapsed ? null : trailing}
    </Link>
  );
}

function Sidebar({ me, areas, openKey, onTasks, counts, collapsed, onToggle, onSearch, onNavigate }: {
  me: Me;
  areas: NavArea[];
  openKey: string | undefined;
  onTasks: boolean;
  counts: TaskCounts;
  collapsed: boolean;
  onToggle?: () => void;
  onSearch: () => void;
  onNavigate?: () => void;
}) {
  const orgName = me.org_name ?? "Your workspace";
  const settings = areas.find((a) => a.section === "admin");
  return (
    <div className={cn("flex h-full flex-col bg-navy text-white", collapsed ? "w-16 px-2" : "w-[248px] px-3")}>
      {/* Brand */}
      <div className={cn("flex h-14 shrink-0 items-center", collapsed ? "justify-center" : "justify-between pl-1")}>
        <Link href="/home" onClick={onNavigate} className="flex items-center gap-2.5" aria-label="Orrfin home">
          <span className="flex size-8 items-center justify-center rounded-lg bg-blue-dark ring-1 ring-white/10">
            <ShieldCheck className="size-[18px] text-cyan" aria-hidden />
          </span>
          {collapsed ? null : <span className="text-[17px] font-semibold tracking-tight">Orrfin</span>}
        </Link>
        {onToggle && !collapsed ? (
          <button type="button" onClick={onToggle} aria-label="Collapse sidebar" title="Collapse sidebar"
                  className="rounded-md p-1.5 text-white/50 hover:bg-sidebar-hover hover:text-white">
            <PanelLeftClose className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>

      {/* Workspace */}
      <DropdownMenu
        align="start"
        triggerLabel={`Workspace: ${orgName}`}
        triggerClassName={cn("flex w-full items-center gap-2.5 rounded-lg bg-white/[0.06] text-left ring-1 ring-white/[0.06] hover:bg-white/10",
          collapsed ? "justify-center p-1.5" : "px-2.5 py-2")}
        trigger={
          <>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-brand-blue text-[13px] font-semibold text-white">
              {orgName.slice(0, 1).toUpperCase()}
            </span>
            {collapsed ? null : (
              <>
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block truncate text-[13px] font-semibold">{orgName}</span>
                  <span className="block truncate text-[11px] text-white/55">{me.plan_name ?? "Growth"} plan</span>
                </span>
                <ChevronsUpDown className="size-4 shrink-0 text-white/45" aria-hidden />
              </>
            )}
          </>
        }
        header={<p className="text-xs text-muted-foreground">Signed in to <span className="font-medium text-heading">{orgName}</span></p>}
        items={accountMenu(me)}
      />

      {/* Search and the one action people take most */}
      <div className={cn("mt-3 flex gap-1.5", collapsed && "flex-col")}>
        <button type="button" onClick={onSearch} title={collapsed ? "Search (Ctrl K)" : undefined}
                className={cn("flex h-9 min-w-0 items-center gap-2 rounded-lg bg-white/[0.06] text-[13px] text-white/60 ring-1 ring-white/[0.06] hover:bg-white/10 hover:text-white",
                  collapsed ? "justify-center" : "flex-1 px-2.5")}>
          <Search className="size-4 shrink-0" aria-hidden />
          {collapsed ? <span className="sr-only">Search</span> : (
            <>
              <span className="flex-1 truncate text-left">Search</span>
              <Kbd onDark>Ctrl K</Kbd>
            </>
          )}
        </button>
        <Link href="/requests/new" onClick={onNavigate} title="New request" aria-label="New request"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-blue text-white hover:bg-brand-bright">
          <FilePlus2 className="size-4" aria-hidden />
        </Link>
      </div>

      {/* Areas */}
      <nav aria-label="Product areas" className="-mx-1 mt-4 min-h-0 flex-1 overflow-y-auto px-1 pb-4">
        {NAV_SECTIONS.filter((s) => s.key !== "admin").map((section) => {
          const inSection = areas.filter((a) => a.section === section.key);
          if (!inSection.length) return null;
          return (
            <div key={section.key} className="mb-4">
              {collapsed ? <div className="mx-2 mb-2 h-px bg-white/10" /> : (
                <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-sidebar-label">{section.label}</p>
              )}
              <ul className="flex flex-col gap-0.5">
                {inSection.map((area) => (
                  <li key={area.key}>
                    <SidebarLink href={area.items[0].href} icon={area.icon} label={area.label} collapsed={collapsed}
                                 active={area.key === openKey && !onTasks} onNavigate={onNavigate} />
                  </li>
                ))}
                {section.key === "main" ? (
                  <li>
                    <SidebarLink href="/tasks" icon={ListTodo} label="My tasks" collapsed={collapsed} active={onTasks}
                                 onNavigate={onNavigate} trailing={<CountPill counts={counts} />} />
                  </li>
                ) : null}
              </ul>
            </div>
          );
        })}
      </nav>

      {/* Settings and the person */}
      <div className="shrink-0 border-t border-white/10 py-3">
        {settings ? (
          <SidebarLink href={settings.items[0].href} icon={settings.icon} label="Settings" collapsed={collapsed}
                       active={settings.key === openKey} onNavigate={onNavigate} />
        ) : null}
        <DropdownMenu
          align="start"
          triggerLabel={`Account: ${me.full_name}`}
          triggerClassName={cn("mt-1 flex w-full items-center gap-2.5 rounded-lg text-left hover:bg-sidebar-hover",
            collapsed ? "justify-center p-1" : "px-2 py-1.5")}
          trigger={
            <>
              <Avatar name={me.full_name} size="sm" />
              {collapsed ? null : (
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block truncate text-[13px] font-medium">{me.full_name}</span>
                  <span className="block truncate text-[11px] text-white/55">{ROLE_LABELS[me.role]}</span>
                </span>
              )}
            </>
          }
          header={
            <div className="text-xs leading-relaxed text-muted-foreground">
              <p className="font-medium text-heading">{me.email}</p>
              {Number(me.approval_limit) > 0 ? <p>Approves up to {formatINR(me.approval_limit)}</p> : null}
            </div>
          }
          items={accountMenu(me)}
        />
        {onToggle && collapsed ? (
          <button type="button" onClick={onToggle} aria-label="Expand sidebar" title="Expand sidebar"
                  className="mt-2 flex w-full justify-center rounded-md p-1.5 text-white/50 hover:bg-sidebar-hover hover:text-white">
            <PanelLeftOpen className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const areas = navigationFor(me.role, me.intake_flow);
  const here = locate(areas, pathname);
  // A page outside the map (the Control Graph, opened from a record) keeps the first area open.
  const openArea = here?.area ?? areas[0];
  const onTasks = pathname === "/tasks";

  // Re-read on every navigation, so the count follows actions taken on the pages.
  const { data: tasks } = useApi<{ overdue: boolean }[]>(`/tasks?at=${encodeURIComponent(pathname)}`);
  const counts: TaskCounts = { total: tasks?.length ?? 0, overdue: tasks?.filter((t) => t.overdue).length ?? 0 };

  useEffect(() => {
    try {
      // Read after the first render, so the server and browser draw the same first frame.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage blocked: start expanded */
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((c) => {
      try { window.localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1"); } catch { /* not remembered, still works */ }
      return !c;
    });
  }

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

  const quickActions: QuickAction[] = [
    { href: "/requests/new", label: me.intake_flow === "need_first" ? "Raise a need" : "New purchase request", icon: FilePlus2 },
    // Step 42: procurement builds POs from approved needs on the Orders page.
    ...(me.intake_flow === "need_first" && ["buyer", "admin"].includes(me.role)
      ? [{ href: "/orders", label: "Create a PO from approved needs", icon: FilePlus2 }] : []),
    { href: "/invoices", label: "Upload an invoice", icon: FileText },
    ...(me.role !== "requester" ? [{ href: "/suppliers", label: "Invite a supplier", icon: Building2 }] : []),
    ...(me.role === "admin" ? [{ href: "/settings/team?invite=1", label: "Invite teammates", icon: UserPlus }] : []),
  ];

  const tabs = openArea.items.length > 1 ? openArea.items : [];
  const sidebarProps = { me, areas, openKey: openArea.key, onTasks, counts, onSearch: () => setPaletteOpen(true) };

  return (
    <div className="flex min-h-screen flex-1">
      <aside className="sticky top-0 hidden h-screen shrink-0 lg:block">
        <Sidebar {...sidebarProps} collapsed={collapsed} onToggle={toggleCollapsed} />
      </aside>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 flex bg-navy/45 lg:hidden" onClick={() => setDrawerOpen(false)}>
          <div className="h-full shadow-overlay" onClick={(event) => event.stopPropagation()}>
            <Sidebar {...sidebarProps} collapsed={false} onNavigate={() => setDrawerOpen(false)}
                     onSearch={() => { setDrawerOpen(false); setPaletteOpen(true); }} />
          </div>
          <button type="button" aria-label="Close menu" className="m-3 self-start rounded-lg bg-white p-2 text-heading">
            <X className="size-4" aria-hidden />
          </button>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-border bg-white">
          <div className="flex h-14 items-center gap-2 px-4 sm:px-6">
            <button type="button" aria-label="Open menu" onClick={() => setDrawerOpen(true)}
                    className="-ml-1 rounded-lg p-2 text-heading hover:bg-ice lg:hidden">
              <Menu className="size-5" aria-hidden />
            </button>
            <div className="flex min-w-0 items-center gap-2.5">
              <openArea.icon className="hidden size-[18px] text-muted-foreground sm:block" aria-hidden />
              <p className="truncate text-[15px] font-semibold text-heading">{onTasks ? "My tasks" : openArea.label}</p>
            </div>

            <div className="ml-auto flex items-center gap-1.5">
              <button type="button" onClick={() => setPaletteOpen(true)} aria-label="Search"
                      className="rounded-lg p-2 text-heading hover:bg-ice lg:hidden">
                <Search className="size-5" aria-hidden />
              </button>
              <button type="button" onClick={() => setAssistantOpen(true)} aria-label="Ask Orrfin"
                      className="flex h-9 items-center gap-2 rounded-lg border border-border bg-white px-3 text-sm font-medium text-heading hover:bg-ice">
                <Sparkles className="size-4 text-brand-blue" aria-hidden />
                <span className="hidden sm:inline">Ask Orrfin</span>
              </button>
              <Link href="/tasks" aria-label={`My tasks: ${counts.total} open${counts.overdue ? `, ${counts.overdue} overdue` : ""}`}
                    className="relative rounded-lg p-2 text-heading hover:bg-ice">
                <Bell className="size-5" aria-hidden />
                {counts.total ? (
                  <span aria-hidden className={cn("absolute right-0.5 top-0.5 min-w-4 rounded-full px-1 text-center text-[10px] font-semibold leading-4 text-white",
                    counts.overdue ? "bg-error" : "bg-primary")}>
                    {counts.total}
                  </span>
                ) : null}
              </Link>
              <div className="lg:hidden">
                <DropdownMenu triggerLabel={`Account: ${me.full_name}`} triggerClassName="rounded-full p-0.5"
                              trigger={<Avatar name={me.full_name} size="sm" />} items={accountMenu(me)} />
              </div>
            </div>
          </div>
          {tabs.length && !onTasks ? (
            <div className="px-4 sm:px-6">
              <LinkTabs label={`${openArea.label} pages`} active={here?.item.href}
                        links={tabs.map((item) => ({ href: item.href, label: item.label }))} />
            </div>
          ) : null}
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-[1360px]">{children}</div>
        </main>
      </div>

      {assistantOpen ? <AssistantPanel onClose={() => setAssistantOpen(false)} /> : null}
      {paletteOpen ? <CommandPalette areas={areas} actions={quickActions} onClose={() => setPaletteOpen(false)} /> : null}
    </div>
  );
}
