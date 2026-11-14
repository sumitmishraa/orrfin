"use client";

/**
 * One contract (BUILD_PLAN change 44): upload the PDF, check each proposed term against the quote
 * it came from, confirm or correct it, then activate. Activation is refused while any term is
 * unconfirmed; the server checks this, the page only shows it.
 */
import { useState } from "react";
import { useParams } from "next/navigation";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { API_URL, APP_HEADERS, post, put } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Term { field: string; value: string; source: string; evidence: { quote: string; page: number; model_id?: string } | null; confirmed_by: string | null }
interface Contract {
  id: string; title: string; status: string; owner_name: string | null; has_file: boolean; terms: Term[]; flags: string[];
  obligations: { id: string; description: string; due_on: string; status: string; owner_name: string | null }[];
}
const FIELDS = ["party", "value", "currency", "start_date", "end_date", "renewal", "notice_days", "payment_terms", "liability_cap", "governing_law"];

export default function ContractPage() {
  const { id } = useParams<{ id: string }>();
  const contract = useApi<Contract>(`/contracts/${id}`);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  if (contract.loading) return <Loading />;
  if (contract.error || !contract.data) return <ErrorNotice message={contract.error ?? "Contract not found."} />;
  const c = contract.data;
  const byField = Object.fromEntries(c.terms.map((t) => [t.field, t]));
  const draft = c.status === "draft";

  async function run(action: () => Promise<Contract>) {
    setError(null);
    try { contract.setData(await action()); } catch (e) { setError(e instanceof Error ? e.message : "That did not work."); }
  }
  async function upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    await run(async () => {
      const response = await fetch(`${API_URL}/contracts/${id}/file`, { method: "POST", body: form, credentials: "same-origin", headers: APP_HEADERS });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed.");
      return body as Contract;
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader title={c.title} description={`${c.status} · owner ${c.owner_name ?? "–"}`}
        actions={draft ? <Button onClick={() => run(() => post<Contract>(`/contracts/${id}/activate`))}>Activate</Button> : undefined} />
      <ErrorNotice message={error} />
      {draft ? (
        <Panel title="Signed contract (PDF)">
          <div className="p-4 text-sm">
            <p className="mb-2 text-muted-foreground">{c.has_file ? "A file is on record. Uploading another proposes terms again; confirmed terms are kept." : "Upload the signed PDF to get proposed terms."}</p>
            <input type="file" accept="application/pdf" aria-label="Contract PDF" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
          </div>
        </Panel>
      ) : null}
      <Panel title="Key terms">
        <ul className="divide-y divide-border">
          {FIELDS.map((field) => {
            const term = byField[field];
            return (
              <li key={field} className="grid gap-2 p-4 text-sm sm:grid-cols-[10rem_1fr_auto]">
                <span className="font-medium capitalize text-heading">{field.replace("_", " ")}</span>
                <div>
                  {draft ? <Input aria-label={field} value={edits[field] ?? term?.value ?? ""} onChange={(e) => setEdits({ ...edits, [field]: e.target.value })} /> : <span>{term?.value ?? "–"}</span>}
                  {term?.evidence ? <p className="mt-1 text-xs text-muted-foreground">Page {term.evidence.page}: “{term.evidence.quote}”</p> : null}
                  <p className="text-xs">{term ? (term.confirmed_by ? `Confirmed by ${term.confirmed_by}` : "Proposed, not confirmed yet") : null}</p>
                </div>
                {draft && (edits[field] ?? term?.value) ? (
                  <Button size="sm" variant="outline" onClick={() => run(() => put<Contract>(`/contracts/${id}/terms/${field}`, { value: edits[field] ?? term?.value }))}>Confirm</Button>
                ) : <span />}
              </li>
            );
          })}
        </ul>
      </Panel>
      {c.flags.length > 0 ? (
        <Panel title="Playbook checks"><ul className="list-disc space-y-1 p-4 pl-8 text-sm">{c.flags.map((f) => <li key={f}>{f}</li>)}</ul></Panel>
      ) : null}
      <Panel title="Obligations">
        {c.obligations.length === 0 ? <p className="p-4 text-sm text-muted-foreground">None yet. Activating a contract with an end date adds a renewal reminder.</p> : (
          <ul className="space-y-2 p-4 text-sm">{c.obligations.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>{o.description} · due {formatDate(o.due_on)} · {o.owner_name} · {o.status}</span>
              {o.status === "open" ? <Button size="sm" variant="outline" onClick={() => run(() => post<Contract>(`/contracts/${id}/obligations/${o.id}/done`))}>Mark done</Button> : null}
            </li>))}</ul>
        )}
      </Panel>
    </div>
  );
}
