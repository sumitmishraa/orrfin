"use client";

/**
 * "Create PO" (Step 42): procurement turns ticked approved needs into one purchase order for one vendor.
 * Needs that describe the same thing start on one line (20 boxes from Riya + 10 from Sameer = 30), and
 * the server also merges lines that end up with the same item code and rate. The item code comes from
 * the ERP's own item list with the last price paid, so the ERP accepts the draft PO later.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { post } from "@/lib/api";
import { formatDate, formatINR, formatQty, lineTotal, requestNumber, sumMoney } from "@/lib/format";
import type { ApprovedNeed, CatalogItem, OrderPoDetail, Vendor } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface Draft {
  key: string;
  description: string;
  needs: ApprovedNeed[];
  item_code: string;
  rate: string;
}

const MONEY = /^\d+(\.\d{1,2})?$/;
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function addQty(needs: ApprovedNeed[]): string {
  return String(needs.reduce((total, n) => total + Number(n.qty), 0));
}

/** The catalog item whose code or description shares the most words with the need. */
function guess(description: string, items: CatalogItem[]): CatalogItem | undefined {
  const words = new Set(norm(description).split(" ").filter((w) => w.length > 2));
  let best: { item: CatalogItem; score: number } | undefined;
  for (const item of items) {
    const have = new Set(norm(`${item.description} ${item.item_code}`).split(" "));
    const score = [...words].filter((w) => have.has(w)).length;
    if (score > 0 && (!best || score > best.score)) best = { item, score };
  }
  return best?.item;
}

export function NewPoDialog({ needs, open, onOpenChange }: {
  needs: ApprovedNeed[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const vendors = useApi<Vendor[]>(open ? "/vendors" : null);
  const items = useApi<CatalogItem[]>(open ? "/ordering/items" : null);
  const [vendorId, setVendorId] = useState("");
  const [note, setNote] = useState("");
  const [edits, setEdits] = useState<Record<string, Partial<Pick<Draft, "item_code" | "rate">>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const drafts: Draft[] = useMemo(() => {
    const groups = new Map<string, ApprovedNeed[]>();
    for (const need of needs) {
      const key = norm(need.description);
      groups.set(key, [...(groups.get(key) ?? []), need]);
    }
    return [...groups.entries()].map(([key, group]) => {
      const suggestion = guess(group[0].description, items.data ?? []);
      return {
        key, description: group[0].description, needs: group,
        item_code: edits[key]?.item_code ?? suggestion?.item_code ?? "",
        rate: edits[key]?.rate ?? suggestion?.last_rate ?? "",
      };
    });
  }, [needs, items.data, edits]);

  const total = sumMoney(drafts.map((d) => lineTotal(addQty(d.needs), MONEY.test(d.rate) ? d.rate : "0")));
  const setDraft = (key: string, field: "item_code" | "rate", value: string) =>
    setEdits((e) => ({ ...e, [key]: { ...e[key], [field]: value } }));

  async function create() {
    if (!vendorId) return setError("Choose the vendor this purchase order goes to.");
    for (const [i, d] of drafts.entries()) {
      if (!d.item_code) return setError(`Line ${i + 1}: choose the ERP item code.`);
      if (!MONEY.test(d.rate) || Number(d.rate) <= 0) return setError(`Line ${i + 1}: enter the agreed rate in rupees.`);
    }
    setBusy(true);
    setError(null);
    try {
      const po = await post<OrderPoDetail>("/ordering/pos", {
        vendor_id: vendorId, note_to_vendor: note,
        lines: drafts.map((d) => {
          const item = items.data?.find((it) => it.item_code === d.item_code);
          return { item_code: d.item_code, rate: d.rate, description: item?.description || d.description,
                   unit: d.needs[0].unit ?? item?.unit ?? null, hsn: item?.hsn ?? null,
                   request_line_ids: d.needs.map((n) => n.request_line_id) };
        }),
      });
      router.push(`/orders/${po.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the purchase order.");
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg" title="Create purchase order"
            description={`${needs.length} approved need line${needs.length === 1 ? "" : "s"} from ${new Set(needs.map((n) => n.request_id)).size} request(s).`}
            footer={
              <div className="flex w-full flex-wrap items-center justify-between gap-3">
                <p className="text-sm">Total before GST <b className="ml-1 text-heading tabular-nums">{formatINR(total)}</b></p>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                  <Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create draft PO"}</Button>
                </div>
              </div>
            }>
      <div className="flex flex-col gap-4">
        <Field label="Vendor (from the ERP)" htmlFor="po-vendor">
          <Select id="po-vendor" value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">Choose…</option>
            {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gstin ? ` · ${v.gstin}` : ""}</option>)}
          </Select>
        </Field>

        {drafts.map((d, i) => {
          const item = items.data?.find((it) => it.item_code === d.item_code);
          return (
            <section key={d.key} className="rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-heading">Line {i + 1}: {d.description}</h3>
                <span className="text-sm tabular-nums text-heading">
                  {formatQty(addQty(d.needs))} {d.needs[0].unit ?? ""} · {formatINR(lineTotal(addQty(d.needs), MONEY.test(d.rate) ? d.rate : "0"))}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                From {d.needs.map((n) => `${requestNumber(n.request_number)} ${n.requester_name} (${formatQty(n.qty)})`).join(" + ")}
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_10rem]">
                <Field label="ERP item code" htmlFor={`item-${i}`}
                       hint={item ? `Last paid ${formatINR(item.last_rate)}${item.last_vendor ? ` to ${item.last_vendor}` : ""}${item.last_date ? ` on ${formatDate(item.last_date)}` : ""}` : "Pick from the ERP's item list."}>
                  <Select id={`item-${i}`} value={d.item_code} onChange={(e) => {
                    setDraft(d.key, "item_code", e.target.value);
                    const picked = items.data?.find((it) => it.item_code === e.target.value);
                    if (picked) setDraft(d.key, "rate", picked.last_rate);
                  }}>
                    <option value="">Choose…</option>
                    {items.data?.map((it) => <option key={it.item_code} value={it.item_code}>{it.item_code} · {it.description}</option>)}
                  </Select>
                </Field>
                <Field label="Rate (₹ each)" htmlFor={`rate-${i}`}>
                  <Input id={`rate-${i}`} inputMode="decimal" value={d.rate} onChange={(e) => setDraft(d.key, "rate", e.target.value)} />
                </Field>
              </div>
            </section>
          );
        })}

        <Field label="Note to the vendor (optional)" htmlFor="po-note" hint="Printed in the email, e.g. the delivery address.">
          <Textarea id="po-note" rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="e.g. Deliver to the Pune office, 2nd floor reception." />
        </Field>
        <p className="text-xs text-muted-foreground">
          Approval depends on the total: within procurement&apos;s limit it is approved when you submit; above it, Finance approves first.
        </p>
        <ErrorNotice message={error} />
      </div>
    </Dialog>
  );
}
