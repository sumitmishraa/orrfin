"use client";

/**
 * Profile & security (Step 41): who you are in this workspace, and two-step sign-in (BUILD_PLAN §9:
 * required for admin and finance). Everyone can open it. A person who just joined as admin or
 * finance lands here with ?setup=mfa, so the second step is the first thing they do.
 *
 * Two-step sign-in: the server makes a secret, the person adds it to an authenticator app, and it is
 * switched on only after a correct 6-digit code proves the app works.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Building2, Gauge, KeyRound, Mail, ShieldAlert, ShieldCheck, Users, Wallet } from "lucide-react";

import { ErrorNotice, PageHeader, Panel } from "@/components/page";
import { useMe } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Avatar, MetaList, StatusPill } from "@/components/ui/display";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { formatINR, ROLE_LABELS } from "@/lib/format";
import { ROLE_SUMMARY } from "@/lib/roles";

const MFA_REQUIRED = ["admin", "finance"];

function TwoStep({ enabledAtStart, highlight }: { enabledAtStart: boolean; highlight: boolean }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(enabledAtStart);
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Something went wrong."); } finally { setBusy(false); }
  }

  const start = () => run(async () => { setSetup(await post("/auth/mfa/setup")); setCode(""); });
  const enable = () => run(async () => {
    await post("/auth/mfa/enable", { code });
    setEnabled(true); setSetup(null); setCode("");
    toast("Two-step sign-in is on", { body: "Next time you sign in, Orrfin asks for a code from your app." });
  });
  const disable = () => run(async () => {
    await post("/auth/mfa/disable", { code });
    setEnabled(false); setCode("");
    toast("Two-step sign-in is off");
  });

  return (
    <Panel title="Two-step sign-in" actions={enabled
      ? <StatusPill tone="success" icon={ShieldCheck}>On</StatusPill>
      : <StatusPill tone="warning" icon={ShieldAlert}>Off</StatusPill>}>
      <div className={highlight && !enabled ? "-m-4 rounded-b-xl bg-ice/50 p-4" : undefined}>
        {enabled ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">You sign in with your password and a 6-digit code from your authenticator app.</p>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Current code, to switch it off" htmlFor="mfa-off" className="w-48">
                <Input id="mfa-off" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code}
                       onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              </Field>
              <Button variant="outline" disabled={busy || code.length < 6} onClick={disable}>Switch off</Button>
            </div>
          </div>
        ) : setup ? (
          <ol className="space-y-4 text-sm">
            <li>
              <p className="font-medium text-heading">1. Add Orrfin to your authenticator app</p>
              <p className="mt-1 text-muted-foreground">In Google Authenticator, Microsoft Authenticator or 1Password, choose &ldquo;Enter a setup key&rdquo; and paste this key:</p>
              <input readOnly value={setup.secret} onFocus={(e) => e.currentTarget.select()} aria-label="Setup key"
                     className="mt-2 w-full max-w-md rounded-lg border border-border bg-ice-light px-3 py-2 font-mono text-sm tracking-wider text-heading" />
            </li>
            <li>
              <p className="font-medium text-heading">2. Enter the 6-digit code the app shows</p>
              <div className="mt-2 flex flex-wrap items-end gap-3">
                <Input aria-label="6-digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code}
                       className="w-40 font-mono tracking-[0.3em]" onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
                <Button disabled={busy || code.length < 6} onClick={enable}>Turn on</Button>
                <Button variant="ghost" onClick={() => setSetup(null)}>Cancel</Button>
              </div>
            </li>
          </ol>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-prose text-sm text-muted-foreground">
              A code from your phone on top of your password, so a stolen password alone can&apos;t open your account.
              {highlight ? <strong className="mt-1 block font-medium text-heading">Your role handles money: please switch this on now.</strong> : null}
            </p>
            <Button onClick={start} disabled={busy}><KeyRound aria-hidden /> Set up two-step sign-in</Button>
          </div>
        )}
        <div className="mt-3"><ErrorNotice message={error} /></div>
      </div>
    </Panel>
  );
}

export default function ProfilePage() {
  const me = useMe();
  const [justJoined, setJustJoined] = useState(false);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("setup") === "mfa") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setJustJoined(true);
      window.history.replaceState(null, "", "/settings");
    }
  }, []);

  const needsMfa = MFA_REQUIRED.includes(me.role) && !me.mfa_enabled;

  return (
    <>
      <PageHeader title="Profile & security" description="Your details in this workspace and how you sign in." />

      {justJoined ? (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-white px-4 py-3 shadow-raised">
          <p className="text-sm text-heading">
            <span className="font-semibold">Welcome to {me.org_name ?? "Orrfin"}.</span>{" "}
            One step left: switch on two-step sign-in below. Then you&apos;re ready.
          </p>
          <Link href="/home" className="text-sm font-medium text-primary hover:underline">Skip for now</Link>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <Panel>
          <div className="flex items-center gap-4">
            <Avatar name={me.full_name} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-lg font-semibold text-heading">{me.full_name}</p>
              <p className="truncate text-sm text-muted-foreground">{me.email}</p>
            </div>
          </div>
          <MetaList className="mt-4" rows={[
            { label: "Workspace", icon: Building2, value: me.org_name ?? "—" },
            { label: "Plan", icon: Gauge, value: me.plan_name ? `${me.plan_name}` : "—" },
            { label: "Role", icon: ShieldCheck, value: ROLE_LABELS[me.role] },
            { label: "Department", icon: Users, value: me.department ?? "—" },
            { label: "Approval limit", icon: Wallet, value: Number(me.approval_limit) > 0 ? formatINR(me.approval_limit) : "None" },
            { label: "Email", icon: Mail, value: me.email },
          ]} />
          <p className="mt-4 rounded-lg bg-ice-light px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            {ROLE_SUMMARY[me.role]} Your admin sets your role, limit and manager{me.role === "admin" ? " (another admin sets yours)" : ""}.
          </p>
        </Panel>

        <div className="space-y-6">
          <TwoStep enabledAtStart={me.mfa_enabled} highlight={justJoined || needsMfa} />
          {me.role === "admin" ? (
            <Panel title="Your team">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">Invite people, set roles and approval limits, and see seat use.</p>
                <Link href="/settings/team" className="text-sm font-medium text-primary hover:underline">Open Team & roles</Link>
              </div>
            </Panel>
          ) : null}
        </div>
      </div>
    </>
  );
}
