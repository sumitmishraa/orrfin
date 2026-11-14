"use client";

/**
 * Legal entities and exchange rates (BUILD_PLAN v3.0 change 38, §5, §6d).
 *
 * An entity is one company of the group. Its tax regime decides how its invoices are checked
 * (India GST or UAE VAT), so only an admin may change it; the server enforces that and this page
 * only hides the buttons. Exchange rates are typed in by finance or an admin and are never
 * overwritten: a correction is a new rate for a new date.
 */
import { useState } from "react";
import { Plus, Star } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { post, put } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Entity {
  id: string; name: string; country: string; base_currency: string; tax_regime: string;
  tax_id: string | null; state_code: string | null; is_default: boolean; active: boolean;
}
interface Rate {
  id: string; base_currency: string; quote_currency: string; rate: string; as_of: string; entered_by_name: string | null;
}

const REGIMES = [
  { value: "in_gst", label: "India (GST)", country: "IN", currency: "INR", taxId: "GSTIN" },
  { value: "ae_vat", label: "UAE (VAT)", country: "AE", currency: "AED", taxId: "TRN" },
] as const;
const CURRENCIES = ["INR", "AED", "USD", "EUR"];
const BLANK = { id: "", name: "", tax_regime: "in_gst", base_currency: "INR", tax_id: "", active: true };

function regimeOf(value: string) {
  return REGIMES.find((r) => r.value === value) ?? REGIMES[0];
}

export default function EntitiesPage() {
  const me = useMe();
  const isAdmin = me.role === "admin";
  const entities = useApi<Entity[]>("/entities");
  const rates = useApi<Rate[]>("/entities/fx-rates");
  const [form, setForm] = useState<typeof BLANK | null>(null);
  const [rate, setRate] = useState({ base_currency: "AED", quote_currency: "INR", rate: "", as_of: new Date().toISOString().slice(0, 10) });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (entities.loading) return <Loading />;
  if (entities.error) return <ErrorNotice message={entities.error} />;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const saveEntity = () => run(async () => {
    if (!form) return;
    const regime = regimeOf(form.tax_regime);
    const body = { name: form.name, country: regime.country, base_currency: form.base_currency,
                   tax_regime: form.tax_regime, tax_id: form.tax_id, active: form.active };
    await (form.id ? put(`/entities/${form.id}`, body) : post("/entities", body));
    setForm(null);
    await entities.reload();
  });
  const makeDefault = (id: string) => run(async () => {
    await post(`/entities/${id}/make-default`);
    await entities.reload();
  });
  const addRate = () => run(async () => {
    await post("/entities/fx-rates", rate);
    setRate({ ...rate, rate: "" });
    await rates.reload();
  });

  const formRegime = form ? regimeOf(form.tax_regime) : REGIMES[0];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Legal entities"
        description="The companies in your group. Each one's country decides how its invoices are checked."
        actions={isAdmin && !form ? <Button onClick={() => setForm(BLANK)}><Plus aria-hidden /> Add entity</Button> : undefined}
      />
      <ErrorNotice message={error} />

      {form ? (
        <Panel title={form.id ? "Edit entity" : "New entity"}>
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Company name" htmlFor="entity-name">
              <Input id="entity-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Country and tax" htmlFor="entity-regime" hint="This picks the invoice checks: GST for India, VAT for the UAE.">
              <Select id="entity-regime" value={form.tax_regime}
                      onChange={(e) => setForm({ ...form, tax_regime: e.target.value, base_currency: regimeOf(e.target.value).currency })}>
                {REGIMES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </Select>
            </Field>
            <Field label={formRegime.taxId} htmlFor="entity-tax-id"
                   hint={formRegime.value === "ae_vat" ? "15 digits starting with 100." : "15 characters, for example 27AAACO1234F1Z5."}>
              <Input id="entity-tax-id" value={form.tax_id} onChange={(e) => setForm({ ...form, tax_id: e.target.value.toUpperCase() })} />
            </Field>
            <Field label="Base currency" htmlFor="entity-currency">
              <Select id="entity-currency" value={form.base_currency} onChange={(e) => setForm({ ...form, base_currency: e.target.value })}>
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </Select>
            </Field>
            {form.id ? (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                In use
              </label>
            ) : null}
            <div className="flex gap-2 sm:col-span-2">
              <Button onClick={saveEntity} disabled={busy}>Save</Button>
              <Button variant="outline" onClick={() => setForm(null)} disabled={busy}>Cancel</Button>
            </div>
          </div>
        </Panel>
      ) : null}

      <div className={table.wrap}>
        <table className={table.table}>
          <thead>
            <tr>{["Entity", "Country and tax", "Tax number", "Currency", "Status", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {(entities.data ?? []).map((e) => (
              <tr key={e.id} className="border-t border-border">
                <td className="px-3 py-2.5 font-medium text-heading">
                  {e.name}{" "}
                  {e.is_default ? <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-ice px-2 py-0.5 text-xs font-medium"><Star className="size-3" aria-hidden /> Default</span> : null}
                </td>
                <td className="px-3 py-2.5">{regimeOf(e.tax_regime).label}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{e.tax_id ?? "Not entered yet"}</td>
                <td className="px-3 py-2.5">{e.base_currency}</td>
                <td className="px-3 py-2.5">{e.active ? "In use" : "Switched off"}</td>
                <td className="px-3 py-2.5 text-right">
                  {isAdmin ? (
                    <span className="inline-flex gap-2">
                      <Button variant="outline" size="sm" disabled={busy}
                              onClick={() => setForm({ id: e.id, name: e.name, tax_regime: e.tax_regime, base_currency: e.base_currency, tax_id: e.tax_id ?? "", active: e.active })}>
                        Edit
                      </Button>
                      {!e.is_default && e.active ? <Button variant="outline" size="sm" disabled={busy} onClick={() => makeDefault(e.id)}>Make default</Button> : null}
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Panel title="Exchange rates">
        <div className="space-y-4 p-4">
          <p className="text-sm text-muted-foreground">
            Typed in by finance, one rate per pair and date. Orrfin never fetches or estimates a rate, and never converts an invoice to make it match.
          </p>
          <div className="grid items-end gap-3 sm:grid-cols-5">
            <Field label="1 unit of" htmlFor="rate-base">
              <Select id="rate-base" value={rate.base_currency} onChange={(e) => setRate({ ...rate, base_currency: e.target.value })}>
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="equals, in" htmlFor="rate-quote">
              <Select id="rate-quote" value={rate.quote_currency} onChange={(e) => setRate({ ...rate, quote_currency: e.target.value })}>
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Rate" htmlFor="rate-value">
              <Input id="rate-value" inputMode="decimal" placeholder="22.6350" value={rate.rate} onChange={(e) => setRate({ ...rate, rate: e.target.value.trim() })} />
            </Field>
            <Field label="On date" htmlFor="rate-date">
              <Input id="rate-date" type="date" value={rate.as_of} onChange={(e) => setRate({ ...rate, as_of: e.target.value })} />
            </Field>
            <Button onClick={addRate} disabled={busy || !rate.rate}>Add rate</Button>
          </div>
          {rates.data && rates.data.length > 0 ? (
            <table className={table.table}>
              <thead>
                <tr>{["Date", "Pair", "Rate", "Entered by"].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rates.data.map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-3 py-2">{formatDate(r.as_of)}</td>
                    <td className="px-3 py-2">1 {r.base_currency} → {r.quote_currency}</td>
                    <td className="px-3 py-2 tabular-nums">{r.rate}</td>
                    <td className="px-3 py-2">{r.entered_by_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <EmptyState>No exchange rates yet. Add one when you first pay in another currency.</EmptyState>}
        </div>
      </Panel>
    </div>
  );
}
