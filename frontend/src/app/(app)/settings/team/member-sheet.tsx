"use client";

/**
 * One team member's details in a right-hand panel (Step 41): their info and settings, what they did
 * recently, and what would be left waiting if they left. The admin changes role, approval limit,
 * manager and department here, and deactivates or reactivates the person. The server refuses what
 * §9 forbids (your own role or limit, the last admin) and the panel shows its reason as given.
 */
import { useEffect, useState } from "react";
import { CalendarClock, Clock, KeyRound, Mail, ShieldCheck, UserCheck, UserX } from "lucide-react";

import { ErrorNotice, Loading } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/controls";
import { Avatar, MetaList, StatusPill } from "@/components/ui/display";
import { Field, Input, Select } from "@/components/ui/field";
import { Dialog, Sheet } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { api, patch, post } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, ROLE_LABELS } from "@/lib/format";
import { ROLE_ORDER } from "@/lib/roles";
import type { Role, TeamMember, TeamMemberDetail } from "@/lib/types";

export function lastSeen(value: string | null): string {
  if (!value) return "Never signed in";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 10) return "Active now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days} day${days === 1 ? "" : "s"} ago` : formatDate(value);
}

const ACTIONS: Record<string, string> = {
  member_joined: "Joined the workspace",
  member_updated: "Settings changed",
  member_deactivated: "Deactivated",
  member_reactivated: "Reactivated",
  mfa_enabled: "Turned on two-step sign-in",
  mfa_disabled: "Turned off two-step sign-in",
};

function describe(action: string): string {
  return ACTIONS[action] ?? action.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function MemberSheet({ memberId, meId, members, onClose, onChanged }: {
  memberId: string | null;
  meId: string;
  members: TeamMember[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [detail, setDetail] = useState<TeamMemberDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [form, setForm] = useState({ role: "requester" as Role, approval_limit: "0", manager_id: "", department: "" });

  useEffect(() => {
    if (!memberId) return;
    let live = true;
    api<TeamMemberDetail>(`/team/members/${memberId}`)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setForm({ role: d.role, approval_limit: d.approval_limit, manager_id: d.manager_id ?? "", department: d.department ?? "" });
        setError(null);
      })
      .catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [memberId]);

  const isMe = detail?.id === meId;
  const dirty = detail && (form.role !== detail.role || form.approval_limit !== detail.approval_limit
    || form.manager_id !== (detail.manager_id ?? "") || form.department !== (detail.department ?? ""));

  async function save() {
    if (!detail) return;
    setSaving(true);
    setError(null);
    const body: Record<string, unknown> = {};
    if (form.role !== detail.role) body.role = form.role;
    if (form.approval_limit !== detail.approval_limit) body.approval_limit = form.approval_limit || "0";
    if (form.manager_id !== (detail.manager_id ?? "")) body.manager_id = form.manager_id || null;
    if (form.department !== (detail.department ?? "")) body.department = form.department;
    try {
      const updated = await patch<TeamMemberDetail>(`/team/members/${detail.id}`, body);
      setDetail(updated);
      setForm({ role: updated.role, approval_limit: updated.approval_limit, manager_id: updated.manager_id ?? "", department: updated.department ?? "" });
      toast(`${updated.full_name} updated`);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  async function setActive(active: boolean) {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await post<TeamMemberDetail>(`/team/members/${detail.id}/${active ? "reactivate" : "deactivate"}`);
      setDetail(updated);
      setConfirming(false);
      toast(active ? `${updated.full_name} can sign in again` : `${updated.full_name} was deactivated`,
        { body: active ? undefined : "They were signed out everywhere. Their history stays in the audit trail." });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change access.");
      setConfirming(false);
    } finally {
      setSaving(false);
    }
  }

  const work = detail?.open_work;
  const waiting = work ? work.open_questions + work.named_approvals : 0;

  return (
    <>
      <Sheet open={Boolean(memberId)} onOpenChange={(open) => !open && onClose()}
             title={detail ? (
               <span className="flex items-center gap-3">
                 <Avatar name={detail.full_name} size="md" />
                 <span className="min-w-0 leading-tight">
                   <span className="block truncate">{detail.full_name}</span>
                   <span className="block truncate text-sm font-normal text-muted-foreground">{detail.email}</span>
                 </span>
               </span>
             ) : "Team member"}
             footer={detail ? (
               <>
                 {detail.status === "active" ? (
                   <Button variant="destructive" className="mr-auto" disabled={saving || isMe} onClick={() => setConfirming(true)}>
                     <UserX aria-hidden /> Deactivate
                   </Button>
                 ) : (
                   <Button variant="outline" className="mr-auto" disabled={saving} onClick={() => setActive(true)}>
                     <UserCheck aria-hidden /> Reactivate
                   </Button>
                 )}
                 <Button disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save changes"}</Button>
               </>
             ) : undefined}>
        {!detail ? (error ? <ErrorNotice message={error} /> : <Loading />) : (
          <Tabs tabs={[
            {
              value: "info", label: "Info", content: (
                <div className="space-y-6">
                  <MetaList rows={[
                    { label: "Status", icon: ShieldCheck, value: detail.status === "active"
                      ? <StatusPill tone="success" icon={UserCheck}>Active</StatusPill>
                      : <StatusPill tone="muted" icon={UserX}>Deactivated</StatusPill> },
                    { label: "Last active", icon: Clock, value: lastSeen(detail.last_seen_at) },
                    { label: "Joined", icon: CalendarClock, value: formatDate(detail.joined_at) },
                    { label: "Invited by", icon: Mail, value: detail.invited_by_name ?? "Workspace owner" },
                    { label: "Two-step sign-in", icon: KeyRound, value: detail.mfa_enabled ? "On" : "Off" },
                  ]} />

                  <section className="space-y-4">
                    <h3 className="text-sm font-semibold text-heading">Role and approvals</h3>
                    {isMe ? (
                      <p className="rounded-lg bg-ice px-3 py-2 text-xs text-heading">
                        You can&apos;t change your own role or approval limit. Another admin can.
                      </p>
                    ) : null}
                    <Field label="Role" htmlFor="member-role">
                      <Select id="member-role" value={form.role} disabled={isMe}
                              onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                        {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                      </Select>
                    </Field>
                    <Field label="Approval limit (₹)" htmlFor="member-limit"
                           hint={`Now ${formatINR(detail.approval_limit)}. Approvals above the limit are refused.`}>
                      <Input id="member-limit" inputMode="decimal" value={form.approval_limit} disabled={isMe}
                             onChange={(e) => setForm({ ...form, approval_limit: e.target.value.replace(/[^\d.]/g, "") })} />
                    </Field>
                    <Field label="Manager" htmlFor="member-manager" hint="Approves this person's requests first.">
                      <Select id="member-manager" value={form.manager_id} onChange={(e) => setForm({ ...form, manager_id: e.target.value })}>
                        <option value="">No manager</option>
                        {members.filter((m) => m.status === "active" && m.id !== detail.id)
                          .map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
                      </Select>
                    </Field>
                    <Field label="Department" htmlFor="member-department">
                      <Input id="member-department" value={form.department} maxLength={80}
                             onChange={(e) => setForm({ ...form, department: e.target.value })} />
                    </Field>
                  </section>
                  <ErrorNotice message={error} />
                </div>
              ),
            },
            {
              value: "activity", label: "Activity", count: detail.activity.length, content: detail.activity.length ? (
                <ol className="relative space-y-4 border-l border-border pl-5">
                  {detail.activity.map((event, i) => (
                    <li key={i} className="relative">
                      <span aria-hidden className="absolute -left-[25px] top-1 size-2.5 rounded-full border-2 border-white bg-brand-bright ring-1 ring-border" />
                      <p className="text-sm text-foreground">{describe(event.action)}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(event.at)}
                        {event.actor_name && event.actor_name !== detail.full_name ? ` · by ${event.actor_name}` : ""}
                        {event.entity_type !== "user" ? ` · ${event.entity_type.replace(/_/g, " ")}` : ""}
                      </p>
                    </li>
                  ))}
                </ol>
              ) : <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>,
            },
            {
              value: "work", label: "Open work", count: waiting, content: (
                <div className="space-y-3 text-sm">
                  <MetaList rows={[
                    { label: "Invoice questions waiting for them", value: work?.open_questions ?? 0 },
                    { label: "Approval steps named to them", value: work?.named_approvals ?? 0 },
                  ]} />
                  <p className="text-muted-foreground">
                    {waiting
                      ? "Before deactivating, ask them to finish these, or change the category reviewer in Rules so the steps go to someone else."
                      : "Nothing is waiting for this person."}
                  </p>
                </div>
              ),
            },
          ]} />
        )}
      </Sheet>

      <Dialog open={confirming} onOpenChange={setConfirming} size="sm" title={`Deactivate ${detail?.full_name ?? ""}?`}
              description="They are signed out at once and can't sign in again until you reactivate them."
              footer={<>
                <Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button>
                <Button variant="destructive" disabled={saving} onClick={() => setActive(false)}>Deactivate</Button>
              </>}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Their past requests, approvals and audit history stay as they are.</li>
          {waiting ? <li className="text-heading">{waiting} item{waiting === 1 ? " is" : "s are"} still waiting for them (see Open work).</li> : null}
          {detail?.uses_seat ? <li>Their power seat becomes free.</li> : null}
        </ul>
      </Dialog>
    </>
  );
}
