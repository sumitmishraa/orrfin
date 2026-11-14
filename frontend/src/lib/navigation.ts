/**
 * The app's navigation map (BUILD_PLAN v3.0 change 37): product areas shown in the rail, and the
 * pages inside each area. The shell, the breadcrumb and the command palette all read this one list.
 *
 * `roles` only decides what a person is shown. The API refuses every call a role may not make
 * (BUILD_PLAN §9), so hiding a link here is a convenience, never a permission.
 * An area is added here in the step that builds its first page; there are no links to pages that
 * do not exist yet.
 */
import {
  ArrowLeftRight, BadgeCheck, Bell, Building2, Cable, CalendarCheck, FilePlus2, FileText, Gauge, Inbox,
  Landmark, ListChecks, Package, Receipt, ScrollText, Settings, ShieldCheck, ShoppingCart, SlidersHorizontal,
  Wallet, Workflow, type LucideIcon,
} from "lucide-react";

import type { Role } from "@/lib/types";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown only to these roles. Left out = shown to everyone. */
  roles?: Role[];
  /** Shows the live count of the user's open tasks next to the label. */
  showsTaskCount?: boolean;
}

export interface NavArea {
  key: string;
  label: string;
  /** One line under the area name in the side panel, saying what the area is for. */
  summary: string;
  icon: LucideIcon;
  items: NavItem[];
}

const FINANCE: Role[] = ["finance", "admin"];
const ADMIN: Role[] = ["admin"];

export const NAV_AREAS: NavArea[] = [
  {
    key: "home", label: "Home", summary: "What needs you today", icon: Gauge,
    items: [
      { href: "/home", label: "Dashboard", icon: Gauge },
      { href: "/tasks", label: "My tasks", icon: Bell, showsTaskCount: true },
      { href: "/inbox", label: "Inbox", icon: Inbox },
      { href: "/notifications", label: "Notifications", icon: Bell },
      { href: "/ask", label: "Ask Orrfin (agents)", icon: Inbox },
    ],
  },
  {
    key: "procure", label: "Procure", summary: "From a request to a purchase order", icon: ShoppingCart,
    items: [
      { href: "/requests", label: "Requests", icon: ListChecks },
      { href: "/requests/new", label: "New request", icon: FilePlus2 },
      { href: "/pos", label: "Purchase orders", icon: Package },
      { href: "/vendors", label: "Vendors", icon: Building2 },
    ],
  },
  {
    key: "pay", label: "Pay", summary: "From an invoice to a reconciled payment", icon: Wallet,
    items: [
      { href: "/invoices", label: "Invoices", icon: FileText },
      { href: "/payments", label: "Payments", icon: Landmark, roles: FINANCE },
      { href: "/cards", label: "Vendor cards", icon: Wallet },
      { href: "/bank", label: "Bank reconciliation", icon: ArrowLeftRight, roles: FINANCE },
      { href: "/close", label: "Month-end close", icon: CalendarCheck, roles: FINANCE },
      { href: "/gst", label: "GSTR-2B", icon: Receipt, roles: FINANCE },
    ],
  },
  {
    key: "controls", label: "Controls", summary: "The rules, and the proof they ran", icon: ShieldCheck,
    items: [
      { href: "/rules", label: "Rules", icon: SlidersHorizontal },
      { href: "/audit", label: "Audit trail", icon: ScrollText },
      { href: "/trust", label: "Trust", icon: BadgeCheck },
    ],
  },
  {
    key: "suppliers", label: "Suppliers", summary: "Onboard and check who you buy from", icon: Building2,
    items: [
      { href: "/suppliers", label: "Onboarding", icon: Building2, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "source", label: "Source", summary: "Quotes, awards and contracts", icon: ScrollText,
    items: [
      { href: "/sourcing", label: "Sourcing (RFQs)", icon: ListChecks, roles: ["buyer", "approver", "finance", "admin"] },
      { href: "/contracts", label: "Contracts", icon: ScrollText, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "automation", label: "Automate", summary: "Who must approve what, and when", icon: Workflow,
    items: [
      { href: "/automation/workflows", label: "Approval workflow", icon: Workflow, roles: ADMIN },
      { href: "/app-studio", label: "App Studio", icon: SlidersHorizontal },
      { href: "/spend", label: "Spend insights", icon: Gauge, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "settings", label: "Settings", summary: "Systems Orrfin is connected to", icon: Settings,
    items: [
      { href: "/connectors", label: "Connectors", icon: Cable, roles: ADMIN },
      { href: "/settings/entities", label: "Legal entities", icon: Building2, roles: FINANCE },
      { href: "/settings/forms", label: "Request forms", icon: ListChecks, roles: ADMIN },
      { href: "/settings/integrations", label: "API & webhooks", icon: Cable },
    ],
  },
];

/** The areas and pages this role is shown; an area with no visible page is dropped. */
export function navigationFor(role: Role): NavArea[] {
  return NAV_AREAS
    .map((area) => ({ ...area, items: area.items.filter((item) => !item.roles || item.roles.includes(role)) }))
    .filter((area) => area.items.length > 0);
}

export interface NavLocation {
  area: NavArea;
  item: NavItem;
}

/**
 * Which page the current address belongs to. The longest matching link wins, so
 * /requests/new lights up "New request" and /requests/abc lights up "Requests".
 */
export function locate(areas: NavArea[], pathname: string): NavLocation | null {
  let best: NavLocation | null = null;
  for (const area of areas) {
    for (const item of area.items) {
      const matches = pathname === item.href || pathname.startsWith(`${item.href}/`);
      if (matches && (!best || item.href.length > best.item.href.length)) best = { area, item };
    }
  }
  return best;
}
