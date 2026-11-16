/** Status pill and number format for Orrfin POs (Step 42). Icon plus words, never colour alone. */
import { Ban, CircleCheck, CircleDot, FilePen, Send, Undo2, XCircle } from "lucide-react";

import { StatusPill, type Tone } from "@/components/ui/display";
import type { OrderPoStatus } from "@/lib/types";

const STATUS: Record<OrderPoStatus, { label: string; tone: Tone; icon: typeof Send }> = {
  draft: { label: "Draft", tone: "neutral", icon: FilePen },
  in_approval: { label: "Waiting for approval", tone: "warning", icon: CircleDot },
  returned: { label: "Returned to procurement", tone: "warning", icon: Undo2 },
  approved: { label: "Approved · ready to send", tone: "info", icon: CircleCheck },
  rejected: { label: "Rejected", tone: "danger", icon: XCircle },
  sent: { label: "Sent to vendor", tone: "success", icon: Send },
  cancelled: { label: "Cancelled", tone: "muted", icon: Ban },
};

export function OrderStatus({ status }: { status: OrderPoStatus }) {
  const s = STATUS[status] ?? STATUS.draft;
  return <StatusPill tone={s.tone} icon={s.icon}>{s.label}</StatusPill>;
}

export const poNumber = (n: number) => `PO-${String(n).padStart(4, "0")}`;
