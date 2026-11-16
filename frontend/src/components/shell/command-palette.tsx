"use client";

/**
 * "Jump to" palette (BUILD_PLAN v3.0 change 37; quick actions added in Step 41): Ctrl+K or the search
 * box in the sidebar opens it, typing filters the quick actions and pages this person can see, Enter
 * goes there. A quick action only opens the page where the action is done; it runs nothing itself,
 * so it needs no permission checks of its own.
 */
import { useMemo, useState, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { CornerDownLeft, Search } from "lucide-react";

import type { NavArea } from "@/lib/navigation";

interface Destination {
  href: string;
  label: string;
  areaLabel: string;
  icon: NavArea["icon"];
}

export interface QuickAction {
  href: string;
  label: string;
  icon: NavArea["icon"];
}

export function CommandPalette({ areas, actions = [], onClose }: { areas: NavArea[]; actions?: QuickAction[]; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);

  const destinations = useMemo<Destination[]>(
    () => [
      ...actions.map((a) => ({ ...a, areaLabel: "Quick action" })),
      ...areas.flatMap((area) => area.items.map((item) => ({
        href: item.href, label: item.label, areaLabel: area.label, icon: item.icon,
      }))),
    ],
    [areas, actions],
  );

  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const results = destinations.filter((d) => {
    const haystack = `${d.label} ${d.areaLabel}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
  // The list shrinks as the person types; keep the highlight on a row that still exists.
  const active = Math.min(highlighted, Math.max(results.length - 1, 0));

  function go(destination: Destination | undefined) {
    if (!destination) return;
    onClose();
    router.push(destination.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted(Math.min(active + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted(Math.max(active - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(results[active]);
    } else if (event.key === "Escape") {
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-navy/45 px-4 pt-[14vh]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Jump to a page"
           className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-white shadow-overlay"
           onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input autoFocus value={query} onKeyDown={onKeyDown}
                 onChange={(event) => { setQuery(event.target.value); setHighlighted(0); }}
                 placeholder="Search pages and actions" aria-label="Search pages and actions"
                 role="combobox" aria-expanded="true" aria-controls="jump-results"
                 aria-activedescendant={results[active] ? `jump-${active}` : undefined}
                 className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
        </div>
        <ul id="jump-results" role="listbox" className="max-h-80 overflow-y-auto p-2">
          {results.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing matches “{query}”.</li>
          ) : results.map((destination, index) => {
            const Icon = destination.icon;
            const selected = index === active;
            return (
              <li key={destination.href} id={`jump-${index}`} role="option" aria-selected={selected}
                  onMouseEnter={() => setHighlighted(index)} onClick={() => go(destination)}
                  className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm ${selected ? "bg-ice text-heading" : ""}`}>
                <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{destination.label}</span>
                <span className="text-xs text-muted-foreground">{destination.areaLabel}</span>
                {selected ? <CornerDownLeft className="size-3.5 text-muted-foreground" aria-hidden /> : null}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
