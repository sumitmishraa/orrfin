"use client";

/**
 * DataTable: the one list layout every Orrfin list page uses (Step 41 design kit).
 *
 *   toolbar: quick search · filter chips · page actions · Columns
 *   table:   optional checkboxes · sortable headers · rows that open the record
 *   footer:  "Total N records · page x of y" · page size
 *
 * Everything here is display: sorting, searching and paging run on rows the page already loaded,
 * so the API's own permission checks are untouched. Below the `md` width each row becomes a card,
 * so the page never scrolls sideways on a phone.
 */
import { useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Columns3, Search, X } from "lucide-react";
import { cn } from "cn";

import { CheckMenu } from "@/components/ui/controls";
import { Skeleton } from "@/components/ui/display";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Makes the header clickable to sort by this value. */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Included in the quick search. */
  searchValue?: (row: T) => string | null | undefined;
  align?: "left" | "right";
  className?: string;
  /** Starts hidden; the person can switch it on from "Columns". */
  defaultHidden?: boolean;
}

export interface FilterChip<T> {
  key: string;
  label: string;
  test: (row: T) => boolean;
}

interface DataTableProps<T> {
  rows: T[] | null | undefined;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  loading?: boolean;
  /** Singular and plural record name for the footer and search placeholder ("invoice", "invoices"). */
  noun?: [string, string];
  onRowClick?: (row: T) => void;
  rowHref?: (row: T) => string;
  filters?: FilterChip<T>[];
  actions?: ReactNode;
  selectable?: boolean;
  bulkActions?: (selected: T[], clear: () => void) => ReactNode;
  empty?: ReactNode;
  initialSort?: { key: string; dir: "asc" | "desc" };
  /** Which filter chip is on when the page opens (a key from `filters`). */
  initialFilter?: string;
  pageSize?: number;
  /** Hides the toolbar and footer, for short tables inside a panel. */
  bare?: boolean;
}

const PAGE_SIZES = [10, 20, 50, 100];

function compare(a: string | number | null | undefined, b: string | number | null | undefined): number {
  if (a === b) return 0;
  if (a === null || a === undefined || a === "") return 1; // blanks always last
  if (b === null || b === undefined || b === "") return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en-IN", { numeric: true, sensitivity: "base" });
}

export function DataTable<T>({
  rows, columns, rowKey, loading = false, noun = ["record", "records"], onRowClick, rowHref, filters, actions,
  selectable = false, bulkActions, empty, initialSort, initialFilter, pageSize: initialPageSize = 20, bare = false,
}: DataTableProps<T>) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [filterKey, setFilterKey] = useState<string | null>(initialFilter ?? null);
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set(columns.filter((c) => c.defaultHidden).map((c) => c.key)));
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const visible = columns.filter((c) => !hidden.has(c.key));
  const searchable = columns.some((c) => c.searchValue);

  const filtered = useMemo(() => {
    let list = rows ?? [];
    const chip = filters?.find((f) => f.key === filterKey);
    if (chip) list = list.filter(chip.test);
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length) {
      list = list.filter((row) => {
        const text = columns.map((c) => c.searchValue?.(row) ?? "").join(" ").toLowerCase();
        return words.every((w) => text.includes(w));
      });
    }
    const column = sort ? columns.find((c) => c.key === sort.key) : undefined;
    if (sort && column?.sortValue) {
      const by = column.sortValue;
      const sign = sort.dir === "asc" ? 1 : -1;
      list = [...list].sort((a, b) => sign * compare(by(a), by(b)));
    }
    return list;
  }, [rows, filters, filterKey, query, sort, columns]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pages - 1);
  const pageRows = bare ? filtered : filtered.slice(current * pageSize, current * pageSize + pageSize);
  const selectedRows = (rows ?? []).filter((r) => selected.has(rowKey(r)));
  const allOnPage = pageRows.length > 0 && pageRows.every((r) => selected.has(rowKey(r)));

  function open(row: T) {
    if (onRowClick) onRowClick(row);
    else if (rowHref) router.push(rowHref(row));
  }
  const clickable = Boolean(onRowClick || rowHref);

  function toggleSort(column: Column<T>) {
    if (!column.sortValue) return;
    setSort((s) => (s?.key === column.key ? { key: column.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: column.key, dir: "asc" }));
  }

  function toggleRow(key: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function togglePage() {
    setSelected((s) => {
      const next = new Set(s);
      for (const r of pageRows) {
        if (allOnPage) next.delete(rowKey(r)); else next.add(rowKey(r));
      }
      return next;
    });
  }

  const toolbar = !bare && (searchable || filters?.length || actions || columns.length > 3);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-white shadow-raised">
      {toolbar ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2.5">
          {searchable ? (
            <label className="relative flex w-full items-center sm:w-auto sm:min-w-56 sm:max-w-72 sm:flex-1">
              <span className="sr-only">Search {noun[1]}</span>
              <Search className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground" aria-hidden />
              <input value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }}
                     placeholder={`Search ${noun[1]}`}
                     className="h-8 w-full rounded-lg border border-border bg-ice-light/60 pl-8 pr-7 text-sm outline-none placeholder:text-muted-foreground focus:border-primary focus:bg-white focus:ring-3 focus:ring-ring/20" />
              {query ? (
                <button type="button" aria-label="Clear search" onClick={() => setQuery("")}
                        className="absolute right-1.5 rounded p-0.5 text-muted-foreground hover:text-heading">
                  <X className="size-3.5" aria-hidden />
                </button>
              ) : null}
            </label>
          ) : null}
          {filters?.length ? (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter">
              {[{ key: null as string | null, label: "All", count: rows?.length ?? 0 },
                ...filters.map((f) => ({ key: f.key as string | null, label: f.label, count: (rows ?? []).filter(f.test).length }))].map((chip) => {
                const active = filterKey === chip.key;
                return (
                  <button key={chip.key ?? "all"} type="button" aria-pressed={active}
                          onClick={() => { setFilterKey(chip.key); setPage(0); }}
                          className={cn("flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors",
                            active ? "border-primary bg-primary text-white" : "border-border bg-white text-heading hover:bg-ice")}>
                    {chip.label}
                    <span className={cn("tabular-nums", active ? "text-white/80" : "text-muted-foreground")}>{chip.count}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {actions}
            {columns.length > 3 ? (
              <CheckMenu
                triggerClassName="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-white px-2.5 text-sm text-heading hover:bg-ice"
                trigger={<><Columns3 className="size-4" aria-hidden /><span className="hidden sm:inline">Columns</span></>}
                options={columns.filter((c) => c.header).map((c) => ({
                  key: c.key, label: c.header, checked: !hidden.has(c.key),
                  onChange: (on) => setHidden((h) => {
                    const next = new Set(h);
                    if (on) next.delete(c.key); else next.add(c.key);
                    return next;
                  }),
                }))}
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {selectable && selectedRows.length ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-ice px-3 py-2 text-sm">
          <span className="font-medium text-heading">{selectedRows.length} selected</span>
          <button type="button" onClick={() => setSelected(new Set())} className="text-primary hover:underline">Clear</button>
          <div className="ml-auto flex gap-2">{bulkActions?.(selectedRows, () => setSelected(new Set()))}</div>
        </div>
      ) : null}

      {/* Table, from md up */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-ice-light">
              {selectable ? (
                <th className="w-10 px-3 py-2.5">
                  <input type="checkbox" aria-label="Select this page" checked={allOnPage} onChange={togglePage}
                         className="size-4 rounded accent-[var(--orffin-blue-medium)]" />
                </th>
              ) : null}
              {visible.map((c) => {
                const sorted = sort?.key === c.key ? sort.dir : null;
                const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
                return (
                  <th key={c.key} scope="col" aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                      className={cn("whitespace-nowrap px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground",
                        c.align === "right" && "text-right", c.className)}>
                    {c.sortValue ? (
                      <button type="button" onClick={() => toggleSort(c)}
                              className={cn("inline-flex items-center gap-1 hover:text-heading", sorted && "text-heading",
                                c.align === "right" && "flex-row-reverse")}>
                        {c.header}
                        <Icon className={cn("size-3.5", !sorted && "opacity-40")} aria-hidden />
                      </button>
                    ) : c.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading && !rows ? Array.from({ length: 5 }, (_, i) => (
              <tr key={i} className="border-b border-border/70 last:border-0">
                {selectable ? <td className="px-3 py-3.5" /> : null}
                {visible.map((c) => <td key={c.key} className="px-3 py-3.5"><Skeleton className="h-4 w-3/4" /></td>)}
              </tr>
            )) : pageRows.map((row) => {
              const key = rowKey(row);
              return (
                <tr key={key}
                    onClick={clickable ? () => open(row) : undefined}
                    onKeyDown={clickable ? (e) => { if (e.key === "Enter" && e.target === e.currentTarget) open(row); } : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    className={cn("border-b border-border/70 last:border-0", selected.has(key) && "bg-ice/60",
                      clickable && "cursor-pointer outline-none hover:bg-ice-light focus-visible:bg-ice")}>
                  {selectable ? (
                    <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label="Select row" checked={selected.has(key)} onChange={() => toggleRow(key)}
                             className="size-4 rounded accent-[var(--orffin-blue-medium)]" />
                    </td>
                  ) : null}
                  {visible.map((c) => (
                    <td key={c.key} className={cn("px-3 py-3 align-middle", c.align === "right" && "text-right", c.className)}>
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Cards, below md */}
      <ul className="divide-y divide-border md:hidden">
        {pageRows.map((row) => {
          const [first, ...rest] = visible;
          return (
            <li key={rowKey(row)}>
              <div role={clickable ? "button" : undefined} tabIndex={clickable ? 0 : undefined}
                   onClick={clickable ? () => open(row) : undefined}
                   onKeyDown={clickable ? (e) => { if (e.key === "Enter") open(row); } : undefined}
                   className={cn("block px-4 py-3", clickable && "active:bg-ice")}>
                {first ? <div className="mb-2 text-sm">{first.cell(row)}</div> : null}
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                  {rest.filter((c) => c.header).map((c) => (
                    <div key={c.key} className="min-w-0">
                      <dt className="text-muted-foreground">{c.header}</dt>
                      <dd className="truncate text-sm text-foreground">{c.cell(row)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </li>
          );
        })}
        {loading && !rows ? <li className="space-y-2 px-4 py-4"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-3/4" /></li> : null}
      </ul>

      {!loading && rows && filtered.length === 0 ? (
        <div className="px-6 py-12 text-center text-sm text-muted-foreground">
          {rows.length === 0 ? (empty ?? `No ${noun[1]} yet.`) : (
            <>No {noun[1]} match. <button type="button" className="text-primary hover:underline"
                     onClick={() => { setQuery(""); setFilterKey(null); }}>Clear search and filters</button></>
          )}
        </div>
      ) : null}

      {rows && filtered.length > 0 && !bare ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-ice-light/50 px-3 py-2 text-sm text-muted-foreground">
          <span>
            Total <strong className="font-semibold text-heading tabular-nums">{filtered.length}</strong>{" "}
            {filtered.length === 1 ? noun[0] : noun[1]}
            {pages > 1 ? <> · page <span className="tabular-nums">{current + 1}</span> of <span className="tabular-nums">{pages}</span></> : null}
          </span>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5">
              <span className="hidden sm:inline">Rows</span>
              <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
                      className="h-7 rounded-md border border-border bg-white px-1.5 text-sm text-heading">
                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <button type="button" aria-label="Previous page" disabled={current === 0} onClick={() => setPage(current - 1)}
                    className="rounded-md border border-border bg-white p-1 text-heading disabled:opacity-40">
              <ChevronLeft className="size-4" aria-hidden />
            </button>
            <button type="button" aria-label="Next page" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}
                    className="rounded-md border border-border bg-white p-1 text-heading disabled:opacity-40">
              <ChevronRight className="size-4" aria-hidden />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
