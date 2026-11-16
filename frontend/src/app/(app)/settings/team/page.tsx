"use client";

/**
 * Team & roles (Step 41, ADR 0011): the admin who bought Orrfin invites the team, sets each person's
 * role, approval limit and manager, and sees how many power seats the plan has left.
 *
 *   seat summary · Members | Pending invites | Roles & permissions
 *
 * Admin only: the sidebar hides it for other roles and the API refuses them (403) either way.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { Ban, Clock, Hourglass, MoreHorizontal, RefreshCw, ShieldCheck, UserCheck, UserPlus, UserX, Users } from "lucide-react";
import { cn } from "cn";

import { ErrorNotice, PageHeader } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { DropdownMenu, Tabs } from "@/components/ui/controls";
import { DataTable, type Column } from "@/components/ui/data-table";
import { PersonCell, StatusPill } from "@/components/ui/display";
import { Dialog } from "@/components/ui/overlay";
import { useToast } from "@/components/ui/toast";
import { api, post } from "@/lib/api";
import { formatDate, formatINR, ROLE_LABELS } from "@/lib/format";
import { CAPABILITIES, POWER_ROLES, ROLE_ORDER, ROLE_SUMMARY, SOD_RULES } from "@/lib/roles";
import type { TeamInvite, TeamMember, TeamPlan } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { InviteDialog } from "./invite-dialog";
import { lastSeen, MemberSheet } from "./member-sheet";

function SeatCard({ plan }: { plan: TeamPlan | null }) {
  const used = plan?.seats_used ?? 0;
  const limit = plan?.seat_limit ?? 0;
  const share = limit ? Math.min(used / limit, 1) : 0;
  const full = plan ? used >= limit : false;
  return (
    <div className="rounded-xl border border-border bg-white p-4 shadow-raised">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Power seats</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-heading">
            {plan ? used : "–"}<span className="text-base font-normal text-muted-foreground"> / {plan ? limit : "–"}</span>
          </p>
        </div>
        <StatusPill tone={full ? "warning" : "info"}>{plan?.plan_name ?? "Plan"} plan</StatusPill>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-ice" role="meter" aria-valuemin={0} aria-valuemax={limit}
           aria-valuenow={used} aria-label="Power seats used">
        <div className={cn("h-full rounded-full transition-[width]", full ? "bg-warning" : "bg-brand-blue")} style={{ width: `${share * 100}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {full ? "All seats in use. Invite people as requesters, or free a seat." : "Buyers, approvers, finance and admins each use a seat. Pending invites hold theirs."}
      </p>
    </div>
  );
}

function Stat({ label, value, note, icon: Icon }: { label: string; value: number | string; note: string; icon: typeof Users }) {
  return (
    <div className="rounded-xl border border-border bg-white p-4 shadow-raised">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        <Icon className="size-4 text-muted-foreground" aria-hidden />
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-heading">{value}</p>
      <p className="mt-2 text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function RolePill({ role }: { role: TeamMember["role"] }) {
  return <StatusPill tone={role === "admin" ? "info" : "neutral"} icon={role === "admin" ? ShieldCheck : undefined}>{ROLE_LABELS[role]}</StatusPill>;
}

function RolesMatrix() {
  const groups = [...new Set(CAPABILITIES.map((c) => c.group))];
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-raised">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border bg-ice-light">
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground">What they can do</th>
              {ROLE_ORDER.map((r) => (
                <th key={r} scope="col" className="px-3 py-3 text-center text-xs font-semibold text-heading">
                  {ROLE_LABELS[r]}
                  <span className="block text-[11px] font-normal text-muted-foreground">{POWER_ROLES.includes(r) ? "Uses a seat" : "Free"}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group}>
                <tr><td colSpan={6} className="bg-ice-light/50 px-4 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{group}</td></tr>
                {CAPABILITIES.filter((c) => c.group === group).map((c) => (
                  <tr key={c.label} className="border-t border-border/70">
                    <td className="px-4 py-2.5 text-foreground">{c.label}</td>
                    {ROLE_ORDER.map((r) => (
                      <td key={r} className="px-3 py-2.5 text-center">
                        {c.roles.includes(r)
                          ? <span className="inline-flex size-5 items-center justify-center rounded-full bg-success/10 text-success" aria-label="Yes">✓</span>
                          : <span className="text-border" aria-label="No">—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <aside className="space-y-4">
        <div className="rounded-xl border border-border bg-white p-4 shadow-raised">
          <h3 className="text-sm font-semibold text-heading">Rules no role can switch off</h3>
          <ul className="mt-3 space-y-2.5 text-sm text-muted-foreground">
            {SOD_RULES.map((rule) => (
              <li key={rule} className="flex gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-brand-blue" aria-hidden />{rule}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-border bg-white p-4 text-sm shadow-raised">
          <h3 className="font-semibold text-heading">In one line</h3>
          <dl className="mt-3 space-y-2.5">
            {ROLE_ORDER.map((r) => (
              <div key={r}><dt className="font-medium text-heading">{ROLE_LABELS[r]}</dt><dd className="text-muted-foreground">{ROLE_SUMMARY[r]}</dd></div>
            ))}
          </dl>
        </div>
      </aside>
    </div>
  );
}

export default function TeamPage() {
  const me = useMe();
  const toast = useToast();
  const { data: plan, reload: reloadPlan } = useApi<TeamPlan>(me.role === "admin" ? "/team/plan" : null);
  const { data: members, error, loading, reload: reloadMembers } = useApi<TeamMember[]>(me.role === "admin" ? "/team/members" : null);
  const { data: invites, reload: reloadInvites } = useApi<TeamInvite[]>(me.role === "admin" ? "/team/invites" : null);
  const [inviting, setInviting] = useState(false);
  const [openMember, setOpenMember] = useState<string | null>(null);
  const [tab, setTab] = useState("members");
  const [freshLink, setFreshLink] = useState<{ email: string; link: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const reloadAll = useCallback(() => { reloadPlan(); reloadMembers(); reloadInvites(); }, [reloadPlan, reloadMembers, reloadInvites]);

  useEffect(() => {
    // "Invite teammates" from the command palette lands here with ?invite=1.
    if (new URLSearchParams(window.location.search).get("invite") === "1") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setInviting(true);
      window.history.replaceState(null, "", "/settings/team");
    }
  }, []);

  if (me.role !== "admin") {
    return (
      <>
        <PageHeader title="Team & roles" />
        <ErrorNotice message="Only an admin can manage the team. Ask your admin to invite someone or change a role." />
      </>
    );
  }

  async function resend(invite: TeamInvite) {
    setActionError(null);
    try {
      const fresh = await post<TeamInvite>(`/team/invites/${invite.id}/resend`);
      setFreshLink({ email: fresh.email, link: fresh.invite_link ?? "" });
      reloadAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not resend.");
    }
  }

  async function revoke(invite: TeamInvite) {
    setActionError(null);
    try {
      await api(`/team/invites/${invite.id}`, { method: "DELETE" });
      toast(`Invitation for ${invite.email} revoked`, { body: "The link no longer works." });
      reloadAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not revoke.");
    }
  }

  const active = members?.filter((m) => m.status === "active") ?? [];
  const pending = invites?.filter((i) => i.status === "pending") ?? [];

  const memberColumns: Column<TeamMember>[] = [
    {
      key: "member", header: "Member", sortValue: (m) => m.full_name, searchValue: (m) => `${m.full_name} ${m.email}`,
      cell: (m) => <PersonCell name={m.full_name} detail={m.email} />,
    },
    { key: "role", header: "Role", sortValue: (m) => ROLE_ORDER.indexOf(m.role), searchValue: (m) => ROLE_LABELS[m.role], cell: (m) => <RolePill role={m.role} /> },
    { key: "department", header: "Department", sortValue: (m) => m.department, searchValue: (m) => m.department, cell: (m) => m.department ?? <span className="text-muted-foreground">—</span> },
    { key: "manager", header: "Manager", sortValue: (m) => m.manager_name, cell: (m) => m.manager_name ?? <span className="text-muted-foreground">—</span> },
    {
      key: "limit", header: "Approval limit", align: "right", sortValue: (m) => Number(m.approval_limit),
      cell: (m) => Number(m.approval_limit) > 0 ? formatINR(m.approval_limit) : <span className="text-muted-foreground">—</span>,
    },
    {
      key: "status", header: "Status", sortValue: (m) => m.status,
      cell: (m) => m.status === "active"
        ? <StatusPill tone="success" icon={UserCheck}>Active</StatusPill>
        : <StatusPill tone="muted" icon={UserX}>Deactivated</StatusPill>,
    },
    { key: "seen", header: "Last active", sortValue: (m) => m.last_seen_at ?? "", cell: (m) => <span className="text-muted-foreground">{lastSeen(m.last_seen_at)}</span> },
    { key: "joined", header: "Joined", defaultHidden: true, sortValue: (m) => m.joined_at, cell: (m) => formatDate(m.joined_at) },
  ];

  const inviteColumns: Column<TeamInvite>[] = [
    { key: "email", header: "Email", sortValue: (i) => i.email, searchValue: (i) => i.email, cell: (i) => <PersonCell name={i.email} detail={i.department ?? undefined} /> },
    { key: "role", header: "Role", cell: (i) => <RolePill role={i.role} /> },
    { key: "by", header: "Invited by", cell: (i) => i.invited_by_name ?? "—" },
    {
      key: "status", header: "Status", sortValue: (i) => i.status,
      cell: (i) => i.status === "pending"
        ? <StatusPill tone="info" icon={Hourglass}>Pending · expires {formatDate(i.expires_at)}</StatusPill>
        : i.status === "expired" ? <StatusPill tone="warning" icon={Clock}>Expired</StatusPill>
          : <StatusPill tone="muted" icon={Ban}>Revoked</StatusPill>,
    },
    { key: "sent", header: "Sent", sortValue: (i) => i.sent_at, cell: (i) => formatDate(i.sent_at) },
    {
      key: "actions", header: "", align: "right", cell: (i) => i.status === "revoked" ? null : (
        <span onClick={(e) => e.stopPropagation()}>
          <DropdownMenu triggerLabel={`Actions for ${i.email}`}
                        triggerClassName="rounded-md p-1.5 text-muted-foreground hover:bg-ice hover:text-heading"
                        trigger={<MoreHorizontal className="size-4" aria-hidden />}
                        items={[
                          { label: "Resend with a new link", icon: RefreshCw, onSelect: () => resend(i) },
                          ...(i.status === "pending" ? [{ label: "Revoke invitation", icon: Ban, danger: true, onSelect: () => revoke(i), separated: true }] : []),
                        ]} />
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Team & roles"
        description="Invite the people who buy, approve and pay. Requesters are free; every other role uses one of your plan's power seats."
        actions={<Button size="lg" onClick={() => setInviting(true)}><UserPlus aria-hidden /> Invite teammates</Button>}
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SeatCard plan={plan} />
        <Stat label="Active members" value={members ? active.length : "–"} icon={Users}
              note={members ? `${members.length - active.length} deactivated` : "Loading…"} />
        <Stat label="Requesters" value={plan?.requesters ?? "–"} icon={Users} note="Free and unlimited on every plan." />
        <Stat label="Pending invites" value={plan?.pending_invites ?? "–"} icon={Hourglass} note="Links expire 7 days after they are sent." />
      </div>

      <ErrorNotice message={error ?? actionError} />

      <Tabs value={tab} onValueChange={setTab} tabs={[
        {
          value: "members", label: "Members", count: members?.length, content: (
            <DataTable rows={members} loading={loading} columns={memberColumns} rowKey={(m) => m.id} noun={["member", "members"]}
                       onRowClick={(m) => setOpenMember(m.id)}
                       filters={[
                         { key: "active", label: "Active", test: (m) => m.status === "active" },
                         { key: "seat", label: "Uses a seat", test: (m) => m.uses_seat && m.status === "active" },
                         { key: "off", label: "Deactivated", test: (m) => m.status === "deactivated" },
                       ]}
                       empty="Only you so far. Invite your team to share the work." />
          ),
        },
        {
          value: "invites", label: "Pending invites", count: pending.length, content: (
            <DataTable rows={invites} columns={inviteColumns} rowKey={(i) => i.id} noun={["invitation", "invitations"]}
                       empty={<>No invitations waiting. <button type="button" className="text-primary hover:underline" onClick={() => setInviting(true)}>Invite teammates</button></>} />
          ),
        },
        { value: "roles", label: "Roles & permissions", content: <RolesMatrix /> },
      ]} />

      <InviteDialog open={inviting} onOpenChange={setInviting} members={members ?? []} plan={plan}
                    onInvited={() => { reloadAll(); setTab("invites"); }} />
      <MemberSheet memberId={openMember} meId={me.id} members={members ?? []} onClose={() => setOpenMember(null)} onChanged={reloadAll} />

      <Dialog open={Boolean(freshLink)} onOpenChange={(o) => !o && setFreshLink(null)} size="md" title="New invitation link"
              description={freshLink ? `For ${freshLink.email}. The previous link no longer works; this one expires in 7 days.` : undefined}
              footer={<>
                <Button variant="outline" onClick={() => setFreshLink(null)}>Close</Button>
                <Button onClick={async () => {
                  try { await navigator.clipboard.writeText(freshLink?.link ?? ""); toast("Link copied"); } catch { /* the field below can be copied by hand */ }
                  setFreshLink(null);
                }}>Copy link</Button>
              </>}>
        <input readOnly value={freshLink?.link ?? ""} onFocus={(e) => e.currentTarget.select()} aria-label="Invitation link"
               className="w-full rounded-lg border border-border bg-ice-light px-3 py-2 font-mono text-xs text-heading" />
      </Dialog>
    </>
  );
}
