"use client";

/**
 * App Studio (BUILD_PLAN change 49): admins define a simple app (questions, who approves, list
 * columns) as JSON-free form fields; everyone creates records; the approver role decides, never the
 * creator. No custom code runs: the definition is data and the server checks every answer.
 */
import { useState } from "react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { post } from "@/lib/api";
import type { FormFieldDef } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface AppDef { id: string; key: string; name: string; fields: FormFieldDef[]; approver_role: string; list_columns: string[] }
interface ListView {
  app: AppDef; columns: { key: string; label: string }[];
  records: { id: string; status: string; values: Record<string, string>; created_by: string; reason: string | null; can_decide: boolean }[];
}

function Records({ app }: { app: AppDef }) {
  const view = useApi<ListView>(`/app-studio/${app.id}/records`);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  async function act(path: string, body: unknown) {
    setError(null);
    try { view.setData(await post<ListView>(path, body)); setValues({}); } catch (e) { setError(e instanceof Error ? e.message : "That did not work."); }
  }
  if (view.loading || !view.data) return <Loading />;
  return (
    <Panel title={`${app.name} (approved by ${app.approver_role})`}>
      <div className="space-y-4 p-4">
        <ErrorNotice message={error} />
        <div className="grid items-end gap-3 sm:grid-cols-3">
          {app.fields.map((f) => (
            <Field key={f.key} label={f.label} htmlFor={`${app.id}-${f.key}`}>
              {f.kind === "choice" ? (
                <Select id={`${app.id}-${f.key}`} value={values[f.key] ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                  <option value="">Choose…</option>{f.options.map((o) => <option key={o}>{o}</option>)}
                </Select>
              ) : <Input id={`${app.id}-${f.key}`} type={f.kind === "date" ? "date" : "text"} value={values[f.key] ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />}
            </Field>
          ))}
          <Button onClick={() => act(`/app-studio/${app.id}/records`, { values })}>Submit</Button>
        </div>
        {view.data.records.length === 0 ? <EmptyState>No records yet.</EmptyState> : (
          <table className={table.table}>
            <thead><tr>{[...view.data.columns.map((c) => c.label), "By", "Status", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr></thead>
            <tbody>{view.data.records.map((r) => (
              <tr key={r.id} className="border-t border-border">
                {view.data!.columns.map((c) => <td key={c.key} className="px-3 py-2">{r.values[c.key] ?? "–"}</td>)}
                <td className="px-3 py-2">{r.created_by}</td><td className="px-3 py-2 capitalize">{r.status}{r.reason ? `: ${r.reason}` : ""}</td>
                <td className="px-3 py-2">{r.can_decide ? (
                  <span className="flex gap-2">
                    <Button size="sm" onClick={() => act(`/app-studio/${app.id}/records/${r.id}/decision`, { decision: "approve" })}>Approve</Button>
                    <Button size="sm" variant="outline" onClick={() => { const reason = window.prompt("Why reject?"); if (reason) void act(`/app-studio/${app.id}/records/${r.id}/decision`, { decision: "reject", reason }); }}>Reject</Button>
                  </span>) : null}</td>
              </tr>))}</tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

export default function AppStudioPage() {
  const me = useMe();
  const apps = useApi<AppDef[]>("/app-studio");
  const [draft, setDraft] = useState({ key: "", name: "", approver_role: "approver", questions: "" });
  const [error, setError] = useState<string | null>(null);
  if (apps.loading) return <Loading />;

  async function create() {
    // One question per line: "Label | kind | option, option". Kinds: text, number, money, date, choice, user.
    const fields = draft.questions.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
      const [label, kind = "text", options = ""] = line.split("|").map((p) => p.trim());
      const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "q";
      return { key: /^[a-z]/.test(key) ? key : `q_${key}`, label, kind, required: true, options: kind === "choice" ? options.split(",").map((o) => o.trim()).filter(Boolean) : [] };
    });
    setError(null);
    try {
      await post("/app-studio", { key: draft.key, name: draft.name, approver_role: draft.approver_role, fields, list_columns: fields.slice(0, 4).map((f) => f.key) });
      setDraft({ key: "", name: "", approver_role: "approver", questions: "" });
      await apps.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the app.");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="App Studio" description="Small approval apps without code: a form, one approver role, and a list." />
      <ErrorNotice message={error} />
      {me.role === "admin" ? (
        <Panel title="Build an app">
          <div className="grid gap-3 p-4 sm:grid-cols-3">
            <Field label="Name" htmlFor="as-name"><Input id="as-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
            <Field label="Key (lower-case, no spaces)" htmlFor="as-key"><Input id="as-key" value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value })} /></Field>
            <Field label="Approved by" htmlFor="as-role">
              <Select id="as-role" value={draft.approver_role} onChange={(e) => setDraft({ ...draft, approver_role: e.target.value })}>
                {["approver", "finance", "admin"].map((r) => <option key={r}>{r}</option>)}
              </Select>
            </Field>
            <Field label="Questions, one per line: Label | kind | options" htmlFor="as-q" className="sm:col-span-3">
              <Textarea id="as-q" value={draft.questions} onChange={(e) => setDraft({ ...draft, questions: e.target.value })} placeholder={"Model | choice | 13 inch, 15 inch\nDays | number"} />
            </Field>
            <div><Button onClick={create} disabled={!draft.name || !draft.key || !draft.questions.trim()}>Save app</Button></div>
          </div>
        </Panel>
      ) : null}
      {(apps.data ?? []).length === 0 ? <EmptyState>No apps yet.</EmptyState> : apps.data?.map((a) => <Records key={a.id} app={a} />)}
    </div>
  );
}
