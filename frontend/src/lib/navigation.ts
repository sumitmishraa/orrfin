/**
 * The app's navigation map (BUILD_PLAN v3.0 change 37, reshaped in Step 41): product areas are the
 * sidebar entries, grouped into sections; the pages inside an area are the tabs across the top of the
 * page (GoHighLevel style). The shell, the tabs and the command palette all read this one list.
 *
 * `roles` only decides what a person is shown. The API refuses every call a role may not make
 * (BUILD_PLAN §9), so hiding a link here is a convenience, never a permission.
 * An area is added here in the step that builds its first page; there are no links to pages that
 * do not exist yet.
 */
import {
  ArrowLeftRight, BadgeCheck, Bell, Building2, Cable, CalendarCheck, FileText, Gauge, Inbox,
  Landmark, ListChecks, Package, Receipt, ScrollText, Settings, ShieldCheck, ShoppingCart, SlidersHorizontal,
  UserCog, Users, Wallet, Workflow, PackagePlus, type LucideIcon,
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
  /** Step 42: shown only in workspaces that use this intake flow. Left out = every workspace. */
  flow?: "need_first" | "buyer_first";
}

export type NavSection = "main" | "operate" | "govern" | "admin";

/** Sidebar section headings, in order. Settings ("admin") sits at the bottom of the sidebar. */
export const NAV_SECTIONS: { key: NavSection; label: string }[] = [
  { key: "main", label: "Main" },
  { key: "operate", label: "Procure to pay" },
  { key: "govern", label: "Control" },
  { key: "admin", label: "Workspace" },
];

export interface NavArea {
  key: string;
  section: NavSection;
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
    key: "home", section: "main", label: "Dashboard", summary: "What needs you today", icon: Gauge,
    items: [
      { href: "/home", label: "Overview", icon: Gauge },
      { href: "/tasks", label: "My tasks", icon: Bell, showsTaskCount: true },
      { href: "/inbox", label: "Inbox", icon: Inbox },
      { href: "/notifications", label: "Notifications", icon: Bell },
      { href: "/ask", label: "Ask Orrfin (agents)", icon: Inbox },
    ],
  },
  {
    key: "procure", section: "operate", label: "Procure", summary: "From a request to a purchase order", icon: ShoppingCart,
    items: [
      { href: "/requests", label: "Requests", icon: ListChecks },
      // Step 42: procurement turns approved needs into POs (need-first workspaces only).
      { href: "/orders", label: "Orders", icon: PackagePlus, roles: ["buyer", "approver", "finance", "admin"], flow: "need_first" },
      { href: "/pos", label: "ERP purchase orders", icon: Package },
      { href: "/vendors", label: "Vendors", icon: Building2 },
    ],
  },
  {
    key: "pay", section: "operate", label: "Pay", summary: "From an invoice to a reconciled payment", icon: Wallet,
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
    key: "controls", section: "govern", label: "Controls", summary: "The rules, and the proof they ran", icon: ShieldCheck,
    items: [
      { href: "/rules", label: "Rules", icon: SlidersHorizontal },
      { href: "/audit", label: "Audit trail", icon: ScrollText },
      { href: "/trust", label: "Trust", icon: BadgeCheck },
    ],
  },
  {
    key: "suppliers", section: "operate", label: "Suppliers", summary: "Onboard and check who you buy from", icon: Building2,
    items: [
      { href: "/suppliers", label: "Onboarding", icon: Building2, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "source", section: "operate", label: "Source", summary: "Quotes, awards and contracts", icon: ScrollText,
    items: [
      { href: "/sourcing", label: "Sourcing (RFQs)", icon: ListChecks, roles: ["buyer", "approver", "finance", "admin"] },
      { href: "/contracts", label: "Contracts", icon: ScrollText, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "automation", section: "govern", label: "Automate", summary: "Who must approve what, and when", icon: Workflow,
    items: [
      { href: "/automation/workflows", label: "Approval workflow", icon: Workflow, roles: ADMIN },
      { href: "/app-studio", label: "App Studio", icon: SlidersHorizontal },
      { href: "/spend", label: "Spend insights", icon: Gauge, roles: ["buyer", "approver", "finance", "admin"] },
    ],
  },
  {
    key: "settings", section: "admin", label: "Settings", summary: "Your profile, your team and connected systems", icon: Settings,
    items: [
      { href: "/settings", label: "Profile & security", icon: UserCog },
      { href: "/settings/team", label: "Team & roles", icon: Users, roles: ADMIN },
      { href: "/settings/entities", label: "Legal entities", icon: Building2, roles: FINANCE },
      { href: "/settings/forms", label: "Request forms", icon: ListChecks, roles: ADMIN },
      { href: "/connectors", label: "ERP connectors", icon: Cable, roles: ADMIN },
      { href: "/settings/integrations", label: "API & webhooks", icon: Cable },
    ],
  },
];

/** The areas and pages this role is shown; an area with no visible page is dropped. */
export function navigationFor(role: Role, flow: "need_first" | "buyer_first" = "buyer_first"): NavArea[] {
  return NAV_AREAS
    .map((area) => ({ ...area, items: area.items.filter((item) =>
      (!item.roles || item.roles.includes(role)) && (!item.flow || item.flow === flow)) }))
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
