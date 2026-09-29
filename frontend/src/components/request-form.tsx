"use client";

/**
 * Intake form (BUILD_PLAN §1 step 1, PROMPTS Step 5): category, title, justification, cost centre,
 * needed-by date, optional suggested vendor and lines. Used to create a request and to edit a
 * draft or returned one. The total shown here is a preview; the server computes the real amount.
 */
import { useState, type FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";

import { ErrorNotice } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { formatINR, lineTotal, sumMoney } from "@/lib/format";
import type { Category, RequestDetail, Vendor } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export interface RequestFormValues {
  category_id: string;
  title: string;
  justification: string;
  cost_center: string;
  needed_by: string | null;
  suggested_vendor_id: string | null;
  lines: { description: string; qty: string; est_rate: string }[];
}

const BLANK_LINE = { description: "", qty: "1", est_rate: "" };
const DECIMAL = /^\d+(\.\d{1,3})?$/;
const MONEY = /^\d+(\.\d{1,2})?$/;

export function RequestForm({
  initial,
  submitLabel,
  onSave,
  secondaryLabel,
  onSecondary,
}: {
  initial?: RequestDetail;
  submitLabel: string;
  onSave: (values: RequestFormValues) => Promise<void>;
  secondaryLabel?: string;
  onSecondary?: (values: RequestFormValues) => Promise<void>;
}) {
  const categories = useApi<Category[]>("/categories");
  const vendors = useApi<Vendor[]>("/vendors");
  const [values, setValues] = useState<RequestFormValues>({
    category_id: initial?.category_id ?? "",
    title: initial?.title ?? "",
    justification: initial?.justification ?? "",
    cost_center: initial?.cost_center ?? "",
    needed_by: initial?.needed_by ?? null,
    suggested_vendor_id: initial?.suggested_vendor_id ?? null,
    lines: initial?.lines.map((l) => ({ description: l.description, qty: l.qty, est_rate: l.est_rate })) ?? [
      { ...BLANK_LINE },
    ],
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof RequestFormValues>(key: K, value: RequestFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));
  const setLine = (i: number, key: "description" | "qty" | "est_rate", value: string) =>
    setValues((v) => ({ ...v, lines: v.lines.map((l, n) => (n === i ? { ...l, [key]: value } : l)) }));

  const total = sumMoney(values.lines.map((l) => lineTotal(l.qty, l.est_rate)));

  function validate(): string | null {
    if (!values.category_id) return "Choose a category.";
    if (!values.title.trim()) return "Give the request a title.";
    for (const [i, line] of values.lines.entries()) {
      if (!line.description.trim()) return `Line ${i + 1}: describe the item.`;
      if (!DECIMAL.test(line.qty) || Number(line.qty) <= 0) return `Line ${i + 1}: quantity must be a number above 0.`;
      if (!MONEY.test(line.est_rate)) return `Line ${i + 1}: enter the estimated rate in rupees, e.g. 78500 or 78500.50.`;
    }
    return null;
  }

  async function run(action: (v: RequestFormValues) => Promise<void>) {
    const problem = validate();
    setError(problem);
    if (problem) return;
    setBusy(true);
    try {
      await action(values);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the request.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(onSave);
      }}
      className="flex flex-col gap-6"
    >
      <div className="grid gap-4 rounded-xl border border-border bg-white p-5 md:grid-cols-2">
        <Field label="Category" htmlFor="category" hint="Decides which buyer handles it.">
          <Select id="category" required value={values.category_id} onChange={(e) => set("category_id", e.target.value)}>
            <option value="">Choose…</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </Field>
        <Field label="Title" htmlFor="title">
          <Input id="title" required maxLength={200} value={values.title} onChange={(e) => set("title", e.target.value)}
                 placeholder="e.g. Laptops for the new analysts" />
        </Field>
        <Field label="Justification" htmlFor="justification" className="md:col-span-2">
          <Textarea id="justification" maxLength={4000} value={values.justification}
                    onChange={(e) => set("justification", e.target.value)} placeholder="Why is this needed?" />
        </Field>
        <Field label="Cost centre" htmlFor="cost_center">
          <Input id="cost_center" maxLength={60} value={values.cost_center}
                 onChange={(e) => set("cost_center", e.target.value)} placeholder="e.g. FIN-OPS" />
        </Field>
        <Field label="Needed by" htmlFor="needed_by">
          <Input id="needed_by" type="date" value={values.needed_by ?? ""}
                 onChange={(e) => set("needed_by", e.target.value || null)} />
        </Field>
        <Field label="Suggested vendor (optional)" htmlFor="vendor" hint="The buyer makes the final choice.">
          <Select id="vendor" value={values.suggested_vendor_id ?? ""}
                  onChange={(e) => set("suggested_vendor_id", e.target.value || null)}>
            <option value="">No suggestion</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="rounded-xl border border-border bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-heading">Items</h2>
        <div className="flex flex-col gap-3">
          {values.lines.map((line, i) => (
            <div key={i} className="grid items-end gap-3 md:grid-cols-[1fr_7rem_10rem_9rem_2.5rem]">
              <Field label={`Line ${i + 1}: description`} htmlFor={`desc-${i}`}>
                <Input id={`desc-${i}`} maxLength={300} value={line.description}
                       onChange={(e) => setLine(i, "description", e.target.value)} />
              </Field>
              <Field label="Qty" htmlFor={`qty-${i}`}>
                <Input id={`qty-${i}`} inputMode="decimal" value={line.qty} onChange={(e) => setLine(i, "qty", e.target.value)} />
              </Field>
              <Field label="Est. rate (₹)" htmlFor={`rate-${i}`}>
                <Input id={`rate-${i}`} inputMode="decimal" value={line.est_rate}
                       onChange={(e) => setLine(i, "est_rate", e.target.value)} />
              </Field>
              <p className="pb-2 text-right text-sm tabular-nums">{formatINR(lineTotal(line.qty, line.est_rate))}</p>
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove line ${i + 1}`}
                      disabled={values.lines.length === 1}
                      onClick={() => setValues((v) => ({ ...v, lines: v.lines.filter((_, n) => n !== i) }))}>
                <Trash2 aria-hidden />
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
          <Button type="button" variant="outline" size="sm"
                  onClick={() => setValues((v) => ({ ...v, lines: [...v.lines, { ...BLANK_LINE }] }))}>
            <Plus aria-hidden /> Add line
          </Button>
          <p className="text-sm">
            Estimated total <span className="ml-2 text-lg font-semibold text-heading tabular-nums">{formatINR(total)}</span>
          </p>
        </div>
      </div>

      <ErrorNotice message={error} />
      <div className="flex gap-2">
        <Button type="submit" size="lg" disabled={busy}>{submitLabel}</Button>
        {secondaryLabel && onSecondary ? (
          <Button type="button" size="lg" variant="outline" disabled={busy} onClick={() => void run(onSecondary)}>
            {secondaryLabel}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
