"use client";

/**
 * API keys and webhooks (BUILD_PLAN v3.0 §5, §9).
 *
 * A key or a webhook secret is shown once, right after it is made; the server keeps only a hash
 * (key) or an encrypted copy (secret) and never sends either again. Everyone manages their own
 * keys; only an admin sees the webhooks section, and the server enforces both.
 */
import { useState } from "react";
import { Copy, KeyRound, Send } from "lucide-react";

import { EmptyState, ErrorNotice, Loading, PageHeader, Panel, table } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, post, put } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface ApiKey { id: string; name: string; prefix: string; expires_at: string; last_used_at: string | null; revoked: boolean }
interface Endpoint { id: string; url: string; events: string[]; active: boolean }
interface Delivery { id: string; event: string; status: string; attempts: number; response_code: number | null; last_error: string | null; at: string }

/** The one moment a new key or secret is visible. */
function ShownOnce({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  return (
    <div role="status" className="space-y-2 rounded-lg border border-primary/40 bg-ice p-3 text-sm">
      <p className="font-medium text-heading">{label} Copy it now: it will not be shown again.</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all rounded bg-white px-2 py-1">{value}</code>
        <Button variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(value)}><Copy aria-hidden /> Copy</Button>
        <Button size="sm" onClick={onDone}>I have saved it</Button>
      </div>
    </div>
  );
}

function Webhooks({ run, busy }: { run: (action: () => Promise<unknown>) => Promise<void>; busy: boolean }) {
  const hooks = useApi<{ events: string[]; endpoints: Endpoint[] }>("/integrations/webhooks");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const [log, setLog] = useState<{ id: string; rows: Delivery[] } | null>(null);

  const add = () => run(async () => {
    const created = await post<{ secret: string }>("/integrations/webhooks", { url, events });
    setSecret(created.secret);
    setUrl("");
    setEvents([]);
    await hooks.reload();
  });
  const showLog = (id: string) => run(async () => setLog({ id, rows: await api<Delivery[]>(`/integrations/webhooks/${id}/deliveries`) }));

  return (
    <Panel title="Webhooks">
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted-foreground">
          Orrfin tells your other systems when something happens. Each message is signed, so the receiver can check it came from Orrfin. Only public https addresses are accepted.
        </p>
        {secret ? <ShownOnce label="Signing secret created." value={secret} onDone={() => setSecret(null)} /> : null}
        <div className="grid items-end gap-3 md:grid-cols-[1fr_auto]">
          <Field label="Address to send to" htmlFor="hook-url">
            <Input id="hook-url" placeholder="https://example.com/orrfin-events" value={url} onChange={(e) => setUrl(e.target.value)} />
          </Field>
          <Button onClick={add} disabled={busy || !url || events.length === 0}>Add webhook</Button>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 md:col-span-2">
            <legend className="mb-1 text-sm font-medium text-heading">Send when</legend>
            {(hooks.data?.events ?? []).map((event) => (
              <label key={event} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={events.includes(event)}
                       onChange={(e) => setEvents(e.target.checked ? [...events, event] : events.filter((x) => x !== event))} />
                {event}
              </label>
            ))}
          </fieldset>
        </div>
        {(hooks.data?.endpoints ?? []).length === 0 ? <EmptyState>No webhooks yet.</EmptyState> : (
          <ul className="space-y-2">
            {hooks.data?.endpoints.map((h) => (
              <li key={h.id} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="break-all font-medium text-heading">{h.url}</p>
                    <p className="text-muted-foreground">{h.events.join(", ")} · {h.active ? "On" : "Switched off"}</p>
                  </div>
                  <span className="inline-flex gap-2">
                    <Button variant="outline" size="sm" disabled={busy || !h.active}
                            onClick={() => run(() => post(`/integrations/webhooks/${h.id}/test`))}><Send aria-hidden /> Send a test</Button>
                    <Button variant="outline" size="sm" disabled={busy} onClick={() => showLog(h.id)}>Recent sends</Button>
                    <Button variant="outline" size="sm" disabled={busy}
                            onClick={() => run(async () => { await put(`/integrations/webhooks/${h.id}/active`, { active: !h.active }); await hooks.reload(); })}>
                      {h.active ? "Switch off" : "Switch on"}
                    </Button>
                  </span>
                </div>
                {log?.id === h.id ? (
                  log.rows.length === 0 ? <p className="mt-2 text-muted-foreground">Nothing sent yet.</p> : (
                    <ul className="mt-2 space-y-1">
                      {log.rows.map((d) => (
                        <li key={d.id}>{formatDate(d.at)} · {d.event} · {d.status}{d.response_code ? ` (${d.response_code})` : ""}{d.last_error ? ` · ${d.last_error}` : ""}</li>
                      ))}
                    </ul>
                  )
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}

export default function IntegrationsPage() {
  const me = useMe();
  const keys = useApi<ApiKey[]>("/integrations/api-keys");
  const [name, setName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (keys.loading) return <Loading />;
  if (keys.error) return <ErrorNotice message={keys.error} />;

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

  const createKey = () => run(async () => {
    const created = await post<{ key: string }>("/integrations/api-keys", { name, days: 90 });
    setNewKey(created.key);
    setName("");
    await keys.reload();
  });

  return (
    <div className="space-y-6">
      <PageHeader title="API & webhooks" description="Let your own tools read from Orrfin, and let Orrfin tell them when something happens." />
      <ErrorNotice message={error} />

      <Panel title="Your API keys">
        <div className="space-y-4 p-4">
          <p className="text-sm text-muted-foreground">
            A key acts as you, with your role, and can only read. It lasts 90 days. Treat it like a password.
          </p>
          {newKey ? <ShownOnce label="Key created." value={newKey} onDone={() => setNewKey(null)} /> : null}
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto]">
            <Field label="What will use this key?" htmlFor="key-name">
              <Input id="key-name" maxLength={120} placeholder="e.g. Monthly spend report" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Button onClick={createKey} disabled={busy || !name.trim()}><KeyRound aria-hidden /> Create key</Button>
          </div>
          {(keys.data ?? []).length === 0 ? <EmptyState>No keys yet.</EmptyState> : (
            <table className={table.table}>
              <thead>
                <tr>{["Name", "Starts with", "Expires", "Last used", ""].map((h) => <th key={h} className={table.th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {keys.data?.map((k) => (
                  <tr key={k.id} className="border-t border-border">
                    <td className="px-3 py-2">{k.name}</td>
                    <td className="px-3 py-2 font-mono text-xs">{k.prefix}…</td>
                    <td className="px-3 py-2">{k.revoked ? "Revoked" : formatDate(k.expires_at)}</td>
                    <td className="px-3 py-2">{k.last_used_at ? formatDate(k.last_used_at) : "Never"}</td>
                    <td className="px-3 py-2 text-right">
                      {!k.revoked ? (
                        <Button variant="outline" size="sm" disabled={busy}
                                onClick={() => run(async () => { await api(`/integrations/api-keys/${k.id}`, { method: "DELETE" }); await keys.reload(); })}>
                          Revoke
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>

      {me.role === "admin" ? <Webhooks run={run} busy={busy} /> : null}
    </div>
  );
}
