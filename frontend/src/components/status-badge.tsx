/**
 * Request status as icon + text label. Status is never shown by colour alone (docs/BRAND.md),
 * because the "approved" blue is also the button blue.
 */
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  FileClock,
  Inbox,
  PackageCheck,
  ShoppingCart,
  Undo2,
  UserRoundSearch,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useOptionalMe } from "@/components/session";
import { StatusPill, type Tone } from "@/components/ui/display";
import type { RequestStatus } from "@/lib/types";

const STATUS: Record<RequestStatus, { label: string; icon: LucideIcon; tone: Tone }> = {
  draft: { label: "Draft", icon: CircleDashed, tone: "muted" },
  submitted: { label: "Admin queue", icon: Inbox, tone: "warning" },
  with_buyer: { label: "With buyer", icon: UserRoundSearch, tone: "info" },
  in_approval: { label: "In approval", icon: FileClock, tone: "warning" },
  returned: { label: "Returned", icon: Undo2, tone: "warning" },
  approved: { label: "Approved · ready for PO", icon: CircleCheck, tone: "success" },
  rejected: { label: "Rejected", icon: CircleX, tone: "danger" },
  po_drafted: { label: "PO drafted", icon: ShoppingCart, tone: "success" },
  po_open: { label: "PO open", icon: PackageCheck, tone: "success" },
  cancelled: { label: "Cancelled", icon: CircleX, tone: "muted" },
};

// Step 42: in need-first workspaces the same statuses mean the need's journey (ADR 0012).
const NEED_FIRST_LABELS: Partial<Record<RequestStatus, string>> = {
  in_approval: "Waiting for manager",
  with_buyer: "With procurement",
  po_drafted: "On a PO",
  po_open: "Ordered",
};

export function StatusBadge({ status }: { status: RequestStatus }) {
  const me = useOptionalMe();
  const base = STATUS[status] ?? STATUS.draft;
  const { icon: Icon, tone } = base;
  const label = (me?.intake_flow === "need_first" && NEED_FIRST_LABELS[status]) || base.label;
  return <StatusPill tone={tone} icon={Icon}>{label}</StatusPill>;
}
