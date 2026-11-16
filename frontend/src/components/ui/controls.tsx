"use client";

/**
 * Menus and tabs for the Step 41 design kit, on Base UI (keyboard and screen-reader behaviour built in).
 *
 * - DropdownMenu: the "⋯" row menu, the workspace switcher and the user menu.
 * - Tabs: switches panels inside one page (the Team page, a record's detail sheet).
 * - LinkTabs: GoHighLevel-style underline tabs that are real links between pages (the area tabs).
 */
import type { ComponentType, ReactElement, ReactNode } from "react";
import Link from "next/link";
import { Menu } from "@base-ui/react/menu";
import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import { Check } from "lucide-react";
import { cn } from "cn";

/* --- DropdownMenu -------------------------------------------------------------------------------- */

export interface MenuAction {
  label: string;
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  onSelect?: () => void;
  href?: string;
  danger?: boolean;
  disabled?: boolean;
  /** Draws a line above this item. */
  separated?: boolean;
}

const itemClass =
  "flex w-full cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none select-none " +
  "data-highlighted:bg-ice data-disabled:opacity-45";

export function DropdownMenu({ trigger, items, align = "end", header, triggerLabel, triggerClassName }: {
  trigger: ReactNode;
  items: MenuAction[];
  align?: "start" | "end";
  header?: ReactNode;
  triggerLabel?: string;
  triggerClassName?: string;
}) {
  return (
    <Menu.Root>
      <Menu.Trigger aria-label={triggerLabel} className={triggerClassName}>{trigger}</Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={6} align={align} className="z-50 outline-none">
          <Menu.Popup className="min-w-52 rounded-lg border border-border bg-white p-1 text-foreground shadow-overlay outline-none transition-[opacity,scale] duration-100 data-ending-style:scale-[0.98] data-ending-style:opacity-0 data-starting-style:scale-[0.98] data-starting-style:opacity-0">
            {header ? <div className="border-b border-border px-2.5 pb-2 pt-1.5 mb-1">{header}</div> : null}
            {items.map((item) => {
              const Icon = item.icon;
              const content = (
                <>
                  {Icon ? <Icon className={cn("size-4 shrink-0", item.danger ? "text-error" : "text-muted-foreground")} aria-hidden /> : null}
                  <span className={item.danger ? "text-error" : undefined}>{item.label}</span>
                </>
              );
              return (
                <div key={item.label}>
                  {item.separated ? <Menu.Separator className="my-1 h-px bg-border" /> : null}
                  {item.href ? (
                    <Menu.LinkItem render={<Link href={item.href} />} className={itemClass}>{content}</Menu.LinkItem>
                  ) : (
                    <Menu.Item className={itemClass} disabled={item.disabled} onClick={item.onSelect}>{content}</Menu.Item>
                  )}
                </div>
              );
            })}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

/** A menu of checkboxes that stays open while ticking, e.g. which table columns to show. */
export function CheckMenu({ trigger, options, triggerClassName }: {
  trigger: ReactNode;
  options: { key: string; label: string; checked: boolean; onChange: (checked: boolean) => void }[];
  triggerClassName?: string;
}) {
  return (
    <Menu.Root>
      <Menu.Trigger className={triggerClassName}>{trigger}</Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={6} align="end" className="z-50 outline-none">
          <Menu.Popup className="min-w-48 rounded-lg border border-border bg-white p-1 shadow-overlay outline-none">
            {options.map((option) => (
              <Menu.CheckboxItem key={option.key} checked={option.checked} onCheckedChange={option.onChange}
                                 closeOnClick={false} className={itemClass}>
                <span className="flex size-4 items-center justify-center rounded border border-border">
                  <Menu.CheckboxItemIndicator><Check className="size-3 text-primary" aria-hidden /></Menu.CheckboxItemIndicator>
                </span>
                {option.label}
              </Menu.CheckboxItem>
            ))}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

/* --- Tabs ---------------------------------------------------------------------------------------- */

export interface TabDef {
  value: string;
  label: string;
  count?: number;
  content: ReactNode;
}

const tabClass =
  "relative -mb-px flex h-10 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-1 text-sm font-medium " +
  "text-muted-foreground outline-none transition-colors hover:text-heading focus-visible:text-heading " +
  "data-active:border-primary data-active:text-heading";

function Count({ value }: { value: number }) {
  return <span className="rounded-full bg-ice px-1.5 text-[11px] font-semibold leading-5 text-heading tabular-nums">{value}</span>;
}

export function Tabs({ tabs, value, onValueChange, className }: {
  tabs: TabDef[];
  value?: string;
  onValueChange?: (value: string) => void;
  className?: string;
}) {
  return (
    <BaseTabs.Root value={value} defaultValue={tabs[0]?.value}
                   onValueChange={onValueChange ? (v) => onValueChange(String(v)) : undefined} className={className}>
      <BaseTabs.List className="flex gap-6 overflow-x-auto overflow-y-hidden border-b border-border [scrollbar-width:none]">
        {tabs.map((tab) => (
          <BaseTabs.Tab key={tab.value} value={tab.value} className={tabClass}>
            {tab.label}
            {tab.count !== undefined ? <Count value={tab.count} /> : null}
          </BaseTabs.Tab>
        ))}
      </BaseTabs.List>
      {tabs.map((tab) => (
        <BaseTabs.Panel key={tab.value} value={tab.value} className="pt-5 outline-none">{tab.content}</BaseTabs.Panel>
      ))}
    </BaseTabs.Root>
  );
}

/** Tabs that navigate. `active` is the href of the current page. */
export function LinkTabs({ links, active, label }: {
  links: { href: string; label: string; badge?: ReactElement | null }[];
  active: string | undefined;
  label: string;
}) {
  return (
    <nav aria-label={label} className="flex gap-6 overflow-x-auto overflow-y-hidden [scrollbar-width:none]">
      {links.map((link) => {
        const current = link.href === active;
        return (
          <Link key={link.href} href={link.href} aria-current={current ? "page" : undefined}
                className={cn(tabClass, current && "border-primary text-heading")}>
            {link.label}
            {link.badge}
          </Link>
        );
      })}
    </nav>
  );
}
