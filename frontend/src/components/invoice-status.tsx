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

const STATUS: Record<string, { label: string; icon: LucideIcon; tone: string }> = {
  extracting: { label: "Reading…", icon: LoaderCircle, tone: "text-muted-foreground bg-muted" },
  needs_review: { label: "Check the fields", icon: FileSearch, tone: "text-warning bg-warning/10" },
  manual_entry: { label: "Manual entry", icon: Keyboard, tone: "text-warning bg-warning/10" },
  confirmed: { label: "Confirmed", icon: PenLine, tone: "text-heading bg-ice" },
  matching: { label: "Matching…", icon: LoaderCircle, tone: "text-muted-foreground bg-muted" },
  matched: { label: "Matched", icon: CircleCheck, tone: "text-success bg-success/10" },
  exception: { label: "Exception", icon: ShieldAlert, tone: "text-error bg-error/10" },
  stale: { label: "Stale: re-match", icon: Undo2, tone: "text-warning bg-warning/10" },
  approved: { label: "Approved · ready for ERP draft", icon: CircleCheck, tone: "text-success bg-success/10" },
  rejected: { label: "Rejected", icon: CircleX, tone: "text-error bg-error/10" },
  correction_requested: { label: "Correction requested", icon: Undo2, tone: "text-warning bg-warning/10" },
};

export function InvoiceStatus({ status }: { status: string }) {
  const { label, icon: Icon, tone } = STATUS[status] ?? { label: status, icon: CircleDashed, tone: "bg-muted" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      <Icon className={`size-3.5 ${status === "extracting" || status === "matching" ? "animate-spin" : ""}`} aria-hidden />
      {label}
    </span>
  );
}
