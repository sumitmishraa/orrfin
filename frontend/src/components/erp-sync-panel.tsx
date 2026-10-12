"use client";

/**
 * ERP write-back status for one document (BUILD_PLAN §8; PROMPTS Steps 14-15): which ERP, the outbox state
 * in plain words, the ERP's document name, the last error, and "Retry sync". Retry never creates a
 * duplicate: the server looks the document up first, and on a confirmed draft it only checks and reports.
 */
import { useEffect, useState } from "react";
import { CircleCheck, CircleX, Clock, Download, RefreshCw } from "lucide-react";

import { ErpBadge } from "@/components/erp-badge";
import { ErrorNotice, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { API_URL, post } from "@/lib/api";
import type { ErpSync } from "@/lib/types";

const STATES: Record<ErpSync["state"], { text: string; icon: typeof Clock; tone: string }> = {
  PENDING: { text: "Queued for the ERP", icon: Clock, tone: "text-muted-foreground" },
  SENT: { text: "Sending to the ERP", icon: Clock, tone: "text-muted-foreground" },
  UNKNOWN: { text: "No answer yet; Orrfin will look it up before trying again", icon: Clock, tone: "text-warning" },
  CONFIRMED: { text: "Draft created", icon: CircleCheck, tone: "text-success" },
  FAILED: { text: "The ERP refused it", icon: CircleX, tone: "text-error" },
};

export function ErpSyncPanel({ sync, note, what, onChange }: {
  sync: ErpSync | null; note?: string | null; what: string; onChange: () => void;
}) {
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = sync !== null && ["PENDING", "SENT", "UNKNOWN"].includes(sync.state);

  useEffect(() => {
    // The worker pushes in the background: refresh until the draft is confirmed or refused.
    if (!inFlight) return;
    const timer = setInterval(onChange, 2500);
    return () => clearInterval(timer);
  }, [inFlight, onChange]);

  if (!sync && !note) return null;
  if (!sync) {
    return (
      <Panel title="ERP draft">
        <p className="text-sm text-muted-foreground">Not sent to the ERP: {note}</p>
      </Panel>
    );
  }
  const current = sync;
  const state = STATES[current.state];
  const Icon = state.icon;

  async function retry() {
    setBusy(true);
    setError(null);
    try {
      const result = await post<{ message: string }>(`/erp-outbox/${current.id}/retry`);
      setMessage(result.message);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`ERP draft ${what}`} actions={<ErpBadge label={current.label} suffix={current.erp} />}>
      <p className={`flex items-center gap-1.5 text-sm font-medium ${state.tone}`}>
        <Icon className="size-4" aria-hidden /> {state.text}
        {current.erp_doc_name ? <span className="font-mono text-heading">· {current.erp_doc_name}</span> : null}
      </p>
      {current.state === "CONFIRMED" ? (
        <p className="mt-1 text-xs text-muted-foreground">
          It is a draft: a person reviews and submits it inside {current.erp}. Orrfin never posts it.
        </p>
      ) : null}
      {current.import_file_url ? (
        <a href={`${API_URL}${current.import_file_url}`} download
           className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline">
          <Download className="size-4" aria-hidden /> Download the import file, then load it in {current.erp}
        </a>
      ) : null}
      {current.last_error ? <div className="mt-2"><ErrorNotice message={current.last_error} /></div> : null}
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={retry} disabled={busy}>
          <RefreshCw className={busy ? "animate-spin" : undefined} aria-hidden /> Retry sync
        </Button>
        {message ? <span role="status" className="text-xs text-muted-foreground">{message}</span> : null}
      </div>
      {error ? <div className="mt-2"><ErrorNotice message={error} /></div> : null}
    </Panel>
  );
}
