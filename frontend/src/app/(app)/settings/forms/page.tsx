"use client";

/**
 * Intake form builder (BUILD_PLAN v3.0 change 40). Admins only; the API refuses everyone else.
 *
 * A request type adds its own questions to the purchase request form. The answers are saved on
 * the request and the approval workflow can route on them. A form only adds questions: it cannot
 * skip an approval or any other control.
 */
import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { post, put } from "@/lib/api";
import type { FormFieldDef, RequestType } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const KINDS: { value: FormFieldDef["kind"]; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "money", label: "Amount of money" },
  { value: "date", label: "Date" },
  { value: "choice", label: "Choice from a list" },
  { value: "user", label: "A person in the company" },
];

interface Draft { id: string | null; key: string; name: string; description: string; active: boolean; fields: FormFieldDef[] }

const NEW_TYPE: Draft = { id: null, key: "", name: "", description: "", active: true, fields: [] };

/** "Annual cost (₹)" → "annual_cost": the name a workflow rule uses for this answer. */
function keyFrom(label: string): string {
  const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return /^[a-z]/.test(key) ? key : key ? `q_${key}`.slice(0, 40) : "";
}

export default function FormBuilderPage() {
  const types = useApi<RequestType[]>("/request-types");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (types.loading) return <Loading />;
  if (types.error) return <ErrorNotice message={types.error} />;

  const savedKeys = new Set(types.data?.find((t) => t.id === draft?.id)?.fields.map((f) => f.key) ?? []);
  const setField = (index: number, change: Partial<FormFieldDef>) =>
    setDraft((d) => d && { ...d, fields: d.fields.map((f, i) => (i === index ? { ...f, ...change } : f)) });
  const move = (index: number, by: number) => setDraft((d) => {
    if (!d || index + by < 0 || index + by >= d.fields.length) return d;
    const fields = [...d.fields];
    [fields[index], fields[index + by]] = [fields[index + by], fields[index]];
    return { ...d, fields };
  });

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const body = { key: draft.key || keyFrom(draft.name), name: draft.name, description: draft.description,
                     active: draft.active, fields: draft.fields };
      await (draft.id ? put(`/request-types/${draft.id}`, body) : post("/request-types", body));
      setDraft(null);
      await types.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the form.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Request forms"
        description="Add your own questions to the purchase request form, one set per type of request."
        actions={!draft ? <Button onClick={() => setDraft(NEW_TYPE)}><Plus aria-hidden /> New request type</Button> : undefined}
      />
      <ErrorNotice message={error} />

      {draft ? (
        <Panel title={draft.id ? `Edit “${draft.name}”` : "New request type"}>
          <div className="space-y-5 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor="type-name" hint="What requesters pick, for example “Software purchase”.">
                <Input id="type-name" maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
              <Field label="Short description" htmlFor="type-description">
                <Input id="type-description" maxLength={500} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              </Field>
            </div>
            {draft.id ? (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />
                Requesters can pick this type
              </label>
            ) : null}

            <ol className="space-y-3">
              {draft.fields.map((field, i) => (
                <li key={i} className="grid items-end gap-3 rounded-lg border border-border p-3 sm:grid-cols-12">
                  <Field label={`Question ${i + 1}`} htmlFor={`q-label-${i}`} className="sm:col-span-4">
                    <Input id={`q-label-${i}`} maxLength={120} value={field.label}
                           onChange={(e) => setField(i, savedKeys.has(field.key)
                             ? { label: e.target.value }  // a saved question keeps its key: workflow rules and old answers use it
                             : { label: e.target.value, key: keyFrom(e.target.value) })} />
                  </Field>
                  <Field label="Answer is" htmlFor={`q-kind-${i}`} className="sm:col-span-3">
                    <Select id={`q-kind-${i}`} value={field.kind}
                            onChange={(e) => setField(i, { kind: e.target.value as FormFieldDef["kind"], options: [] })}>
                      {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </Select>
                  </Field>
                  {field.kind === "choice" ? (
                    <Field label="Options, separated by commas" htmlFor={`q-options-${i}`} className="sm:col-span-3">
                      <Input id={`q-options-${i}`} defaultValue={field.options.join(", ")}
                             onBlur={(e) => setField(i, { options: e.target.value.split(",").map((o) => o.trim()).filter(Boolean) })} />
                    </Field>
                  ) : <span className="hidden sm:col-span-3 sm:block" />}
                  <div className="flex items-center gap-1 sm:col-span-2">
                    <label className="mr-auto flex items-center gap-1.5 text-sm">
                      <input type="checkbox" checked={field.required} onChange={(e) => setField(i, { required: e.target.checked })} />
                      Required
                    </label>
                    <Button variant="ghost" size="icon" aria-label={`Move question ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp aria-hidden /></Button>
                    <Button variant="ghost" size="icon" aria-label={`Move question ${i + 1} down`} disabled={i === draft.fields.length - 1} onClick={() => move(i, 1)}><ArrowDown aria-hidden /></Button>
                    <Button variant="ghost" size="icon" aria-label={`Remove question ${i + 1}`}
                            onClick={() => setDraft({ ...draft, fields: draft.fields.filter((_, n) => n !== i) })}><Trash2 aria-hidden /></Button>
                  </div>
                  {field.key ? <p className="text-xs text-muted-foreground sm:col-span-12">In a workflow rule this answer is called <code>custom.{field.key}</code>.</p> : null}
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={draft.fields.length >= 40}
                      onClick={() => setDraft({ ...draft, fields: [...draft.fields, { key: "", label: "", kind: "text", required: false, options: [] }] })}>
                <Plus aria-hidden /> Add a question
              </Button>
              <Button onClick={save} disabled={busy || !draft.name.trim()}>Save form</Button>
              <Button variant="outline" onClick={() => { setDraft(null); setError(null); }} disabled={busy}>Cancel</Button>
            </div>
          </div>
        </Panel>
      ) : null}

      {(types.data ?? []).length === 0 && !draft ? (
        <EmptyState>No request types yet. Requesters see the standard form until you add one.</EmptyState>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {(types.data ?? []).map((t) => (
            <li key={t.id} className="rounded-xl border border-border bg-white p-4 shadow-raised">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-heading">{t.name}</h2>
                  <p className="text-sm text-muted-foreground">{t.description || "No description"}</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setDraft({ ...t, fields: t.fields.map((f) => ({ ...f })) })}>Edit</Button>
              </div>
              <p className="mt-3 text-sm">
                {t.fields.length === 0 ? "No extra questions" : `${t.fields.length} extra question${t.fields.length === 1 ? "" : "s"}: ${t.fields.map((f) => f.label).join(", ")}`}
              </p>
              {!t.active ? <p className="mt-1 text-xs font-medium text-muted-foreground">Switched off</p> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
