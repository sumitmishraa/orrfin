"use client";

/**
 * Accept a team invitation (Step 41, ADR 0011, §9): the link from the admin opens this page, the
 * person sees who invited them, to which workspace and with which role, then sets their name and
 * password. The link works once and for 7 days; the server decides, this page only reports it.
 * Admin and finance go straight on to switch on two-step sign-in (§9); everyone else lands on Home.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Building2, CircleAlert, LoaderCircle, ShieldCheck, UserRound } from "lucide-react";

import { ErrorNotice, Loading } from "@/components/page";
import { AuthLayout } from "@/components/shell/auth-layout";
import { Button } from "@/components/ui/button";
import { Avatar, MetaList } from "@/components/ui/display";
import { Field, Input } from "@/components/ui/field";
import { api, post } from "@/lib/api";
import { ROLE_SUMMARY } from "@/lib/roles";
import type { Role } from "@/lib/types";

interface Invitation {
  email: string;
  role: Role;
  role_name: string;
  org_name: string;
  invited_by_name: string | null;
  department: string | null;
  expires_at: string;
  needs_mfa: boolean;
}

const MIN_PASSWORD = 12;

export default function JoinPage() {
  const router = useRouter();
  // Kept in a ref, never in rendered state, so the token is not written into the page.
  const token = useRef("");
  const [invite, setInvite] = useState<Invitation | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Only the first run reads the address: in development React runs this effect twice.
    if (!token.current) token.current = new URLSearchParams(window.location.search).get("token") ?? "";
    // Drop the token from the address bar, so it isn't left in history or shared by copy-paste.
    window.history.replaceState(null, "", "/join");
    if (!token.current) {
       
      setLookupError("This page needs the link from your invitation email.");
      return;
    }
    api<Invitation>(`/team/invites/lookup/${encodeURIComponent(token.current)}`)
      .then(setInvite)
      .catch((e: Error) => setLookupError(e.message));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!fullName.trim()) return setError("Enter your full name.");
    if (password.length < MIN_PASSWORD) return setError(`Choose a password of at least ${MIN_PASSWORD} characters.`);
    if (password !== again) return setError("The two passwords are not the same.");
    setBusy(true);
    setError(null);
    try {
      await post("/auth/accept-invite", { token: token.current, full_name: fullName.trim(), password });
      router.replace(invite?.needs_mfa ? "/settings?setup=mfa" : "/home");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not join.");
      setBusy(false);
    }
  }

  if (lookupError) {
    return (
      <AuthLayout>
        <div className="rounded-xl border border-border bg-white p-6">
          <CircleAlert className="size-6 text-warning" aria-hidden />
          <h1 className="mt-3 text-xl font-semibold text-heading">This invitation can&apos;t be used</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {lookupError} Invitation links work once and expire after 7 days. Ask your admin to resend it from Team &amp; roles.
          </p>
          <Link href="/login" className="mt-5 inline-block text-sm font-medium text-primary hover:underline">Already have an account? Sign in</Link>
        </div>
      </AuthLayout>
    );
  }

  if (!invite) return <AuthLayout><Loading label="Checking your invitation…" /></AuthLayout>;

  return (
    <AuthLayout>
      <div className="flex items-center gap-3">
        <Avatar name={invite.invited_by_name ?? invite.org_name} size="md" />
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-heading">{invite.invited_by_name ?? "Your admin"}</span> invited you to join
        </p>
      </div>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight text-heading">{invite.org_name} on Orrfin</h1>

      <div className="mt-5 rounded-xl border border-border bg-white px-4 py-1">
        <MetaList rows={[
          { label: "Your email", icon: UserRound, value: invite.email },
          { label: "Role", icon: ShieldCheck, value: invite.role_name },
          ...(invite.department ? [{ label: "Department", icon: Building2, value: invite.department }] : []),
        ]} />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{ROLE_SUMMARY[invite.role]}</p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        <Field label="Full name" htmlFor="join-name">
          <Input id="join-name" autoComplete="name" required value={fullName} className="h-10" autoFocus
                 onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label="Choose a password" htmlFor="join-password" hint={`At least ${MIN_PASSWORD} characters.`}>
          <Input id="join-password" type="password" autoComplete="new-password" required value={password} className="h-10"
                 onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Type it again" htmlFor="join-again">
          <Input id="join-again" type="password" autoComplete="new-password" required value={again} className="h-10"
                 onChange={(e) => setAgain(e.target.value)} />
        </Field>
        <ErrorNotice message={error} />
        <Button type="submit" size="lg" disabled={busy} className="h-10 w-full">
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
          Join {invite.org_name}
        </Button>
        {invite.needs_mfa ? (
          <p className="text-center text-xs text-muted-foreground">Next, you&apos;ll switch on two-step sign-in. Your role handles money.</p>
        ) : null}
      </form>
    </AuthLayout>
  );
}
