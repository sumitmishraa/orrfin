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

import type { RequestStatus } from "@/lib/types";

const STATUS: Record<RequestStatus, { label: string; icon: LucideIcon; tone: string }> = {
  draft: { label: "Draft", icon: CircleDashed, tone: "text-muted-foreground bg-muted" },
  submitted: { label: "Admin queue", icon: Inbox, tone: "text-warning bg-warning/10" },
  with_buyer: { label: "With buyer", icon: UserRoundSearch, tone: "text-heading bg-ice" },
  in_approval: { label: "In approval", icon: FileClock, tone: "text-warning bg-warning/10" },
  returned: { label: "Returned", icon: Undo2, tone: "text-warning bg-warning/10" },
  approved: { label: "Approved · ready for PO", icon: CircleCheck, tone: "text-success bg-success/10" },
  rejected: { label: "Rejected", icon: CircleX, tone: "text-error bg-error/10" },
  po_drafted: { label: "PO drafted", icon: ShoppingCart, tone: "text-success bg-success/10" },
  po_open: { label: "PO open", icon: PackageCheck, tone: "text-success bg-success/10" },
  cancelled: { label: "Cancelled", icon: CircleX, tone: "text-muted-foreground bg-muted" },
};

export function StatusBadge({ status }: { status: RequestStatus }) {
  const { label, icon: Icon, tone } = STATUS[status] ?? STATUS.draft;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      <Icon className="size-3.5" aria-hidden />
      {label}
    </span>
  );
}
