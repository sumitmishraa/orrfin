/**
 * The honesty label every ERP connector carries (BUILD_PLAN §13 claims policy, docs/ERP_CONNECTORS.md §1):
 * Live = a real running copy of the ERP; Sandbox = the vendor's official test API; Simulated = fixtures in
 * the vendor's published API format. Icon + text, never colour alone (docs/BRAND.md).
 */
import { FlaskConical, Radio, ServerCog } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ErpLabel } from "@/lib/types";

const LABELS: Record<ErpLabel, { text: string; icon: LucideIcon; tone: string; title: string }> = {
  live: { text: "Live", icon: Radio, tone: "text-success bg-success/10",
          title: "Connected to a real running copy of this ERP" },
  sandbox: { text: "Sandbox", icon: ServerCog, tone: "text-warning bg-warning/10",
             title: "The vendor's official read-only test API" },
  simulated: { text: "Simulated", icon: FlaskConical, tone: "text-muted-foreground bg-muted",
               title: "Built to the vendor's published API; not connected to a live system" },
};

export function ErpBadge({ label, suffix }: { label: ErpLabel; suffix?: string }) {
  const { text, icon: Icon, tone, title } = LABELS[label];
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      <Icon className="size-3.5" aria-hidden />
      {text}
      {suffix ? ` · ${suffix}` : ""}
    </span>
  );
}
