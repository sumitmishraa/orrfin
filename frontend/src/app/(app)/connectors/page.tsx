"use client";

/**
 * Connectors (PROMPTS Step 12, BUILD_PLAN §4 connector rules, ADR 0006): one card per ERP Orrfin can plug into.
 * Every ERP has a Simulated mode (fixtures in its published API format). ERPs with a free test system also
 * have a Live mode: paste the keys → Test connection → Prepare demo data → Make active.
 * Keys are write-only: the server returns "saved …1234", never a value, so this page never holds a secret
 * after the form is sent. Admin only; the server enforces it.
 */
import { useState } from "react";
import { CircleCheck, CircleX, KeyRound, LoaderCircle, PlugZap, RotateCcw, Unplug } from "lucide-react";

import { ErpBadge } from "@/components/erp-badge";
import { EmptyState, ErrorNotice, Loading, PageHeader } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { api, ApiError, post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ConnectionCheck, ConnectionInfo, ConnectorCard, Job } from "@/lib/types";
import { useApi } from "@/lib/use-api";

async function waitForJob(job: Job, onProgress: (text: string) => void): Promise<Job> {
  // Preparing a live ERP can take a minute (it creates ~100 records); stop waiting after ~3 minutes.
  for (let i = 0; i < 180 && (job.status === "queued" || job.status === "running"); i++) {
    await new Promise((r) => setTimeout(r, 1000));
    job = await api<Job>(`/jobs/${job.id}`);
    onProgress(job.status === "running" ? "Working in the ERP…" : "Queued…");
  }
  return job;
}

function seedSummary(job: Job): string {
  const created = Object.entries(job.result?.created ?? {}).map(([k, n]) => `${n} ${k}`);
  const notes = job.result?.notes ?? [];
  return [created.length ? `Created ${created.join(", ")}.` : "Nothing new to create.", ...notes].join(" ");
}

function CheckList({ check }: { check: ConnectionCheck | null }) {
  if (!check?.steps.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-xs">
      {check.steps.map((s) => (
        <li key={s.name} className="flex items-start gap-1.5">
          {s.ok ? <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-success" aria-label="Passed" />
                : <CircleX className="mt-0.5 size-3.5 shrink-0 text-error" aria-label="Needs attention" />}
          <span><span className="font-medium">{s.name}:</span> {s.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function StatusLine({ info }: { info: ConnectionInfo }) {
  const text = { not_connected: "Not tested yet", connected: "Connection works", error: "Needs attention" }[info.status];
  return (
    <p className="text-xs text-muted-foreground">
      {text}
      {info.last_checked_at ? ` · checked ${formatDateTime(info.last_checked_at)}` : ""}
    </p>
  );
}

function Card({ card, onChange }: { card: ConnectorCard; onChange: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = card.simulated?.is_active || card.live?.is_active;

  async function run(label: string, action: () => Promise<string | void>) {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      const text = await action();
      if (text) setMessage(text);
      onChange();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  const saveKeys = () => run("save", async () => {
    await api(`/connectors/${card.system}/credentials`, { method: "PUT", body: JSON.stringify({ values }) });
    setValues({}); // the typed secrets leave the page as soon as the server has them
    return "Keys saved (encrypted). Now click Test connection.";
  });
  const test = (info: ConnectionInfo) => run("test", async () => {
    const check = await post<ConnectionCheck>(`/connectors/connections/${info.id}/test`);
    return check.ok ? "Connection works." : "The test found a problem; see below.";
  });
  const prepare = (info: ConnectionInfo) => run("prepare", async () => {
    let job = await post<Job>(`/connectors/connections/${info.id}/prepare`);
    job = await waitForJob(job, setMessage);
    if (job.status === "failed") throw new Error(`Prepare failed: ${job.last_error}`);
    if (job.status !== "done") throw new Error("Still working. Is the worker running? (scripts\\dev.ps1 starts it.)");
    return seedSummary(job);
  });
  const activate = (info: ConnectionInfo) => run("activate", async () => {
    await post(`/connectors/connections/${info.id}/activate`);
    return `${card.name} (${info.mode}) is now the active ERP. Go to POs → Sync from ERP.`;
  });
  const disconnect = () => run("disconnect", async () => {
    await api(`/connectors/${card.system}/credentials`, { method: "DELETE" });
    return "Keys removed from Orrfin.";
  });

  return (
    <section className={`flex flex-col rounded-xl border bg-white p-4 ${active ? "border-brand-bright shadow-sm" : "border-border"}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold text-heading">{card.name}</h2>
          <p className="text-xs text-muted-foreground">{card.segment}</p>
        </div>
        {active ? <span className="rounded-full bg-ice px-2 py-0.5 text-xs font-medium text-heading">Active</span> : null}
      </div>

      {!card.built ? (
        <p className="mt-3 text-sm text-muted-foreground">Arrives in Step {card.step}.</p>
      ) : (
        <>
          <div className="mt-3 rounded-lg bg-ice-light p-3">
            <div className="flex items-center justify-between gap-2">
              <ErpBadge label="simulated" />
              {card.simulated && !card.simulated.is_active ? (
                <Button size="xs" variant="outline" disabled={busy !== null} onClick={() => activate(card.simulated!)}>
                  Use simulated
                </Button>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Built to {card.name}&apos;s published API. Not connected to a live system.{card.note ? ` ${card.note}` : ""}
            </p>
            {card.capabilities ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Draft bill = {card.capabilities.draft_bill_means}. Draft PO = {card.capabilities.draft_po_means}.
                {card.capabilities.write_note ? ` ${card.capabilities.write_note}` : ""}
              </p>
            ) : null}
            {card.simulated?.is_active ? (
              <Button size="xs" variant="ghost" className="mt-1" disabled={busy !== null} onClick={() => prepare(card.simulated!)}>
                <RotateCcw aria-hidden /> Reset demo data
              </Button>
            ) : null}
          </div>

          {card.has_live_mode ? (
            <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); void saveKeys(); }}>
              <div className="flex items-center justify-between gap-2">
                <ErpBadge label={card.live_label} suffix={card.live ? undefined : "not set up"} />
                {card.live ? <StatusLine info={card.live} /> : null}
              </div>
              <p className="text-xs text-muted-foreground">Sign up: {card.signup}. Steps in docs/CONNECT_ERPS.md.</p>
              {card.fields.map((f) => {
                const saved = card.live?.fields[f.name];
                const placeholder = saved?.set
                  ? (f.secret ? `saved ${saved.hint} (leave blank to keep)` : saved.hint)
                  : f.placeholder;
                return (
                  <label key={f.name} className="block text-xs">
                    <span className="font-medium text-heading">{f.label}{f.required ? "" : " (optional)"}</span>
                    <input
                      type={f.secret ? "password" : "text"} autoComplete="off" spellCheck={false}
                      name={`${card.system}-${f.name}`} placeholder={placeholder} value={values[f.name] ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                      className="mt-1 w-full rounded-lg border border-border px-2 py-1.5 text-sm outline-none focus:border-brand-bright" />
                    {f.help ? <span className="mt-0.5 block text-muted-foreground">{f.help}</span> : null}
                  </label>
                );
              })}
              <div className="flex flex-wrap gap-2 pt-1">
                <Button size="sm" type="submit" disabled={busy !== null || Object.values(values).every((v) => !v)}>
                  <KeyRound aria-hidden /> Save keys
                </Button>
                {card.live ? (
                  <>
                    <Button size="sm" type="button" variant="outline" disabled={busy !== null} onClick={() => test(card.live!)}>
                      <PlugZap aria-hidden /> Test connection
                    </Button>
                    <Button size="sm" type="button" variant="outline"
                            disabled={busy !== null || card.live.status !== "connected"} onClick={() => prepare(card.live!)}>
                      Prepare demo data
                    </Button>
                    <Button size="sm" type="button"
                            disabled={busy !== null || card.live.status !== "connected" || card.live.is_active}
                            onClick={() => activate(card.live!)}>
                      Make active
                    </Button>
                    <Button size="sm" type="button" variant="ghost" disabled={busy !== null} onClick={disconnect}>
                      <Unplug aria-hidden /> Disconnect
                    </Button>
                  </>
                ) : null}
              </div>
              {card.live?.last_error && card.live.status === "error" ? <ErrorNotice message={card.live.last_error} /> : null}
              <CheckList check={card.live?.last_check ?? null} />
            </form>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              No free test system exists for {card.name}, so it stays Simulated until a customer gives Orrfin a test system.
            </p>
          )}
        </>
      )}

      {busy ? (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> {message ?? "Working…"}
        </p>
      ) : message ? (
        <p role="status" className="mt-2 text-xs text-success">{message}</p>
      ) : null}
      {error ? <div className="mt-2"><ErrorNotice message={error} /></div> : null}
    </section>
  );
}

export default function ConnectorsPage() {
  const me = useMe();
  const { data, error, loading, reload } = useApi<ConnectorCard[]>(me.role === "admin" ? "/connectors" : null);
  if (me.role !== "admin") {
    return <EmptyState>Only an admin can manage ERP connectors.</EmptyState>;
  }
  const active = data?.find((c) => c.simulated?.is_active || c.live?.is_active);
  const activeInfo = active ? (active.live?.is_active ? active.live : active.simulated) : null;
  return (
    <>
      <PageHeader
        title="ERP connectors"
        description={active && activeInfo ? `Active ERP: ${active.name} (${activeInfo.label}). Sync, matching and draft write-back use it.`
                                           : "Choose which ERP Orrfin reads from and drafts into."} />
      <ErrorNotice message={error} />
      {loading ? <Loading /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data?.map((card) => <Card key={card.system} card={card} onChange={reload} />)}
        </div>
      )}
    </>
  );
}
