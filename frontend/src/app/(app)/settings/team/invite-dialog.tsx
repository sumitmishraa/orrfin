"use client";

/**
 * "Invite teammates" (Step 41, ADR 0011): paste one or many emails, choose one role for all of them,
 * and get a single-use link per person. Requesters are free; other roles show that they use a power
 * seat, and the server refuses an invite that would go over the plan. Locally there is no mail
 * server, so the admin copies each link and sends it themselves.
 */
import { useState, type ClipboardEvent, type KeyboardEvent } from "react";
import { Check, CircleAlert, Copy, Mail, X } from "lucide-react";
import { cn } from "cn";

import { ErrorNotice } from "@/components/page";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/display";
import { Field, Input, Select } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { ROLE_LABELS } from "@/lib/format";
import { POWER_ROLES, ROLE_ORDER, ROLE_SUMMARY } from "@/lib/roles";
import type { InviteResult, Role, TeamMember, TeamPlan } from "@/lib/types";

const SPLIT = /[\s,;]+/;
const LIMIT_ROLES: Role[] = ["approver", "finance", "admin"];

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this invitation link:", link);
    }
  }
  return (
    <Button type="button" size="sm" variant="outline" onClick={copy}>
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : "Copy link"}
    </Button>
  );
}

export function InviteDialog({ open, onOpenChange, members, plan, onInvited }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  members: TeamMember[];
  plan: TeamPlan | null;
  onInvited: () => void;
}) {
  const toast = useToast();
  const [emails, setEmails] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [role, setRole] = useState<Role>("requester");
  const [limit, setLimit] = useState("0");
  const [managerId, setManagerId] = useState("");
  const [department, setDepartment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<InviteResult[] | null>(null);

  const freeSeats = plan ? Math.max(plan.seat_limit - plan.seats_used, 0) : null;
  const departments = [...new Set(members.map((m) => m.department).filter(Boolean))] as string[];
  const managers = members.filter((m) => m.status === "active");

  function addEmails(text: string) {
    const found = text.split(SPLIT).map((e) => e.trim().toLowerCase()).filter(Boolean);
    if (!found.length) return;
    setEmails((all) => [...all, ...found.filter((e) => !all.includes(e))]);
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (["Enter", ",", " ", ";", "Tab"].includes(event.key) && draft.trim()) {
      event.preventDefault();
      addEmails(draft);
    } else if (event.key === "Backspace" && !draft && emails.length) {
      setEmails((all) => all.slice(0, -1));
    }
  }

  function onPaste(event: ClipboardEvent<HTMLInputElement>) {
    const text = event.clipboardData.getData("text");
    if (SPLIT.test(text.trim())) {
      event.preventDefault();
      addEmails(text);
    }
  }

  function reset() {
    setEmails([]); setDraft(""); setRole("requester"); setLimit("0"); setManagerId(""); setDepartment("");
    setError(null); setResults(null);
  }

  async function submit() {
    const all = draft.trim() ? [...emails, ...draft.split(SPLIT).filter(Boolean)] : emails;
    if (!all.length) {
      setError("Enter at least one email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await post<{ results: InviteResult[] }>("/team/invites", {
        emails: all, role, approval_limit: LIMIT_ROLES.includes(role) ? limit || "0" : "0",
        manager_id: managerId || null, department: department || null,
      });
      setResults(response.results);
      setDraft("");
      const sent = response.results.filter((r) => r.status === "invited").length;
      if (sent) toast(`${sent} invitation${sent === 1 ? "" : "s"} created`, { body: "Copy each link and send it to the person." });
      onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the invitations.");
    } finally {
      setBusy(false);
    }
  }

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) window.setTimeout(reset, 200);
  }

  if (results) {
    return (
      <Dialog open={open} onOpenChange={close} size="lg" title="Invitations ready"
              description="Each link works once and expires in 7 days. Only the person you send it to should open it."
              footer={<>
                <Button variant="outline" onClick={reset}>Invite more people</Button>
                <Button onClick={() => close(false)}>Done</Button>
              </>}>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {results.map((r) => (
            <li key={r.email} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
              <Mail className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.email}</span>
              {r.status === "invited" && r.invite_link ? (
                <>
                  <StatusPill tone="success" icon={Check}>Invited</StatusPill>
                  <CopyLink link={r.invite_link} />
                </>
              ) : (
                <StatusPill tone="warning" icon={CircleAlert}>{r.message ?? "Not invited"}</StatusPill>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          This is a local demo with no mail server: the &ldquo;email&rdquo; is written to the server log. Copy the link and
          send it yourself. You can get a fresh link any time from <span className="font-medium text-heading">Pending invites</span>.
        </p>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={close} size="lg" title="Invite teammates"
            description="They get a link to set their own password and join with the role you choose."
            footer={<>
              <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
              <Button onClick={submit} disabled={busy}>
                {busy ? "Sending…" : `Send ${emails.length + (draft.trim() ? 1 : 0) || ""} invitation${emails.length + (draft.trim() ? 1 : 0) === 1 ? "" : "s"}`}
              </Button>
            </>}>
      <div className="space-y-5">
        <Field label="Email addresses" htmlFor="invite-emails" hint="Paste a list, or press Enter after each address.">
          <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-white px-2 py-1.5 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
            {emails.map((email) => (
              <span key={email} className="flex items-center gap-1 rounded-md bg-ice py-0.5 pl-2 pr-1 text-sm text-heading">
                {email}
                <button type="button" aria-label={`Remove ${email}`} onClick={() => setEmails((all) => all.filter((e) => e !== email))}
                        className="rounded p-0.5 text-muted-foreground hover:bg-white hover:text-heading">
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            ))}
            <input id="invite-emails" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown}
                   onPaste={onPaste} onBlur={() => draft.trim() && addEmails(draft)} autoFocus
                   placeholder={emails.length ? "" : "priya@company.com, rahul@company.com"}
                   className="h-7 min-w-40 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
          </div>
        </Field>

        <fieldset>
          <legend className="mb-1.5 flex w-full items-center justify-between text-sm font-medium text-heading">
            Role
            {freeSeats !== null ? (
              <span className="text-xs font-normal text-muted-foreground">
                {freeSeats} of {plan?.seat_limit} power seats free · requesters are always free
              </span>
            ) : null}
          </legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {ROLE_ORDER.map((r) => {
              const checked = role === r;
              const seat = POWER_ROLES.includes(r);
              return (
                <label key={r} className={cn("flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors",
                  checked ? "border-primary bg-ice/60 ring-1 ring-primary" : "border-border hover:bg-ice-light",
                  r === "admin" && "sm:col-span-2")}>
                  <input type="radio" name="invite-role" value={r} checked={checked} onChange={() => setRole(r)}
                         className="mt-0.5 size-4 accent-[var(--orffin-blue-medium)]" />
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-sm font-medium text-heading">
                      {ROLE_LABELS[r]}
                      <span className={cn("rounded px-1.5 text-[11px] font-medium leading-5",
                        seat ? "bg-ice text-heading" : "bg-success/10 text-success")}>
                        {seat ? "Uses a seat" : "Free"}
                      </span>
                    </span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{ROLE_SUMMARY[r]}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-3">
          {LIMIT_ROLES.includes(role) ? (
            <Field label="Approval limit (₹)" htmlFor="invite-limit" hint="Approvals above this are refused.">
              <Input id="invite-limit" inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value.replace(/[^\d.]/g, ""))} />
            </Field>
          ) : null}
          <Field label="Manager" htmlFor="invite-manager" hint="Approves their requests first.">
            <Select id="invite-manager" value={managerId} onChange={(e) => setManagerId(e.target.value)}>
              <option value="">No manager</option>
              {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
            </Select>
          </Field>
          <Field label="Department" htmlFor="invite-department">
            <Input id="invite-department" list="invite-departments" value={department} maxLength={80}
                   onChange={(e) => setDepartment(e.target.value)} placeholder="e.g. Operations" />
            <datalist id="invite-departments">{departments.map((d) => <option key={d} value={d} />)}</datalist>
          </Field>
        </div>
        <ErrorNotice message={error} />
      </div>
    </Dialog>
  );
}
