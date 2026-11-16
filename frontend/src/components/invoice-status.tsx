/**
 * Invoice status (and match outcome) as icon + text. Never colour alone (docs/BRAND.md).
 */
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  FileSearch,
  Keyboard,
  LoaderCircle,
  PenLine,
  ShieldAlert,
  Undo2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { StatusPill, type Tone } from "@/components/ui/display";

const STATUS: Record<string, { label: string; icon: LucideIcon; tone: Tone }> = {
  extracting: { label: "Reading…", icon: LoaderCircle, tone: "muted" },
  needs_review: { label: "Check the fields", icon: FileSearch, tone: "warning" },
  manual_entry: { label: "Manual entry", icon: Keyboard, tone: "warning" },
  confirmed: { label: "Confirmed", icon: PenLine, tone: "info" },
  matching: { label: "Matching…", icon: LoaderCircle, tone: "muted" },
  matched: { label: "Matched", icon: CircleCheck, tone: "success" },
  exception: { label: "Exception", icon: ShieldAlert, tone: "danger" },
  stale: { label: "Stale: re-match", icon: Undo2, tone: "warning" },
  approved: { label: "Approved · ready for ERP draft", icon: CircleCheck, tone: "success" },
  rejected: { label: "Rejected", icon: CircleX, tone: "danger" },
  correction_requested: { label: "Correction requested", icon: Undo2, tone: "warning" },
};

export function InvoiceStatus({ status }: { status: string }) {
  const { label, icon, tone } = STATUS[status] ?? { label: status, icon: CircleDashed, tone: "muted" as Tone };
  const busy = status === "extracting" || status === "matching";
  return <StatusPill tone={tone} icon={icon} className={busy ? "[&_svg]:animate-spin" : undefined}>{label}</StatusPill>;
}
