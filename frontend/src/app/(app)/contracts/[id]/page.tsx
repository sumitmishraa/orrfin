"use client";

/**
 * One contract (BUILD_PLAN change 44): upload the PDF, check each proposed term against the quote
 * it came from, confirm or correct it, then activate. Activation is refused while any term is
 * unconfirmed; the server checks this, the page only shows it.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, CircleDashed, TriangleAlert, Upload } from "lucide-react";

import { AsideCard, BackLink, DetailLayout } from "@/components/detail";
import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { MetaList, StatusPill } from "@/components/ui/display";
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

  const confirmed = FIELDS.filter((f) => byField[f]?.confirmed_by).length;

  return (
    <>
      <PageHeader meta={<BackLink href="/contracts" label="Contracts" />} title={c.title}
        description={`Owner ${c.owner_name ?? "–"}`}
        actions={
          <span className="flex items-center gap-2">
            <StatusPill tone={c.status === "active" ? "success" : c.status === "draft" ? "muted" : "warning"}><span className="capitalize">{c.status}</span></StatusPill>
            {draft ? <Button onClick={() => run(() => post<Contract>(`/contracts/${id}/activate`))}>Activate</Button> : null}
          </span>
        } />
      <DetailLayout
        aside={
          <>
            <AsideCard title="Contract">
              <MetaList rows={[
                { label: "Status", value: <span className="capitalize">{c.status}</span> },
                { label: "Owner", value: c.owner_name ?? "—" },
                { label: "Signed PDF", value: c.has_file ? "On record" : "Not uploaded" },
                { label: "Terms confirmed", value: `${confirmed} of ${FIELDS.length}` },
              ]} />
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ice" aria-hidden>
                <div className="h-full rounded-full bg-brand-blue" style={{ width: `${(confirmed / FIELDS.length) * 100}%` }} />
              </div>
            </AsideCard>
            {c.flags.length > 0 ? (
              <AsideCard title="Playbook checks">
                <ul className="space-y-2 py-1 text-sm">
                  {c.flags.map((f) => <li key={f} className="flex gap-2"><TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />{f}</li>)}
                </ul>
              </AsideCard>
            ) : null}
            <AsideCard title="Obligations">
              {c.obligations.length === 0 ? <p className="py-1 text-sm text-muted-foreground">None yet. Activating a contract with an end date adds a renewal reminder.</p> : (
                <ul className="divide-y divide-border/70 text-sm">{c.obligations.map((o) => (
                  <li key={o.id} className="space-y-1.5 py-2.5">
                    <p className="font-medium text-heading">{o.description}</p>
                    <p className="text-xs text-muted-foreground">Due {formatDate(o.due_on)} · {o.owner_name ?? "No owner"} · {o.status}</p>
                    {o.status === "open" ? <Button size="sm" variant="outline" onClick={() => run(() => post<Contract>(`/contracts/${id}/obligations/${o.id}/done`))}>Mark done</Button> : null}
                  </li>))}</ul>
              )}
            </AsideCard>
          </>
        }
        main={
          <>
            <ErrorNotice message={error} />
            {draft ? (
              <Panel title="Signed contract (PDF)">
                <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                  <p className="text-muted-foreground">{c.has_file ? "A file is on record. Uploading another proposes terms again; confirmed terms are kept." : "Upload the signed PDF to get proposed terms, each with the text it came from."}</p>
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-white px-3 py-1.5 font-medium text-heading hover:bg-ice">
                    <Upload className="size-4" aria-hidden /> Choose PDF
                    <input type="file" accept="application/pdf" aria-label="Contract PDF" className="sr-only"
                           onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
                  </label>
                </div>
              </Panel>
            ) : null}
            <Panel title="Key terms">
              <ul className="-my-1 divide-y divide-border/70">
                {FIELDS.map((field) => {
                  const term = byField[field];
                  return (
                    <li key={field} className="grid gap-2 py-3 text-sm sm:grid-cols-[10rem_1fr_auto] sm:items-start">
                      <span className="pt-1.5 font-medium capitalize text-heading">{field.replace("_", " ")}</span>
                      <div className="min-w-0">
                        {draft ? <Input aria-label={field} value={edits[field] ?? term?.value ?? ""} onChange={(e) => setEdits({ ...edits, [field]: e.target.value })} /> : <span className="block pt-1.5">{term?.value ?? "–"}</span>}
                        {term?.evidence ? <p className="mt-1.5 rounded-md bg-ice-light px-2 py-1 text-xs text-muted-foreground">Page {term.evidence.page}: “{term.evidence.quote}”</p> : null}
                        {term ? (
                          <p className="mt-1.5">
                            {term.confirmed_by
                              ? <StatusPill tone="success" icon={CircleCheck}>Confirmed by {term.confirmed_by}</StatusPill>
                              : <StatusPill tone="warning" icon={CircleDashed}>Proposed, not confirmed yet</StatusPill>}
                          </p>
                        ) : null}
                      </div>
                      {draft && (edits[field] ?? term?.value) ? (
                        <Button size="sm" variant="outline" onClick={() => run(() => put<Contract>(`/contracts/${id}/terms/${field}`, { value: edits[field] ?? term?.value }))}>Confirm</Button>
                      ) : <span />}
                    </li>
                  );
                })}
              </ul>
            </Panel>
          </>
        }
      />
    </>
  );
}
