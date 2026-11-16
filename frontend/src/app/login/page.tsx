"use client";

/**
 * Login page (BUILD_PLAN §3 Auth, PROMPTS Step 3; Step 41 layout): email + password, then the
 * 6-digit code for people who switched on two-step sign-in (§9). The server decides when a code is
 * needed; this page shows the code field once the server has asked for it.
 * The demo accounts listed below are fictional and exist only in the local synthetic demo.
 */
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";

import { ApiStatus } from "@/components/api-status";
import { ErrorNotice } from "@/components/page";
import { AuthLayout } from "@/components/shell/auth-layout";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/display";
import { Field, Input } from "@/components/ui/field";
import { ApiError, post } from "@/lib/api";

const DEMO_USERS = [
  { email: "riya.requester@demo.orrfin.ai", name: "Riya Sharma", role: "Requester" },
  { email: "arjun.buyer@demo.orrfin.ai", name: "Arjun Mehta", role: "Buyer" },
  { email: "neha.approver@demo.orrfin.ai", name: "Neha Iyer", role: "Approver" },
  { email: "vikram.finance@demo.orrfin.ai", name: "Vikram Rao", role: "Finance" },
  { email: "anita.admin@demo.orrfin.ai", name: "Anita Desai", role: "Admin" },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", { email, password, code: needsCode ? code : undefined });
      router.replace("/home");
    } catch (e) {
      // The server answers 401 with a message about the code when this account has two-step sign-in on.
      if (e instanceof ApiError && e.status === 401 && /code/i.test(e.message)) {
        if (needsCode) setError(e.message);
        setNeedsCode(true);
      } else {
        setError(e instanceof Error ? e.message : "Login failed.");
      }
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <h1 className="text-2xl font-semibold tracking-tight text-heading">{needsCode ? "Enter your code" : "Sign in"}</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">
        {needsCode ? "Open your authenticator app and type the 6-digit code for Orrfin." : "Welcome back. Use your work email."}
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        {needsCode ? (
          <Field label="6-digit code" htmlFor="code">
            <Input id="code" inputMode="numeric" autoComplete="one-time-code" autoFocus required maxLength={8} value={code}
                   className="h-11 font-mono text-lg tracking-[0.4em]" onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          </Field>
        ) : (
          <>
            <Field label="Work email" htmlFor="email">
              <Input id="email" type="email" autoComplete="username" required value={email} className="h-10"
                     onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" required value={password} className="h-10"
                     onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </>
        )}
        <ErrorNotice message={error} />
        <Button type="submit" size="lg" disabled={busy} className="h-10 w-full">
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
          {needsCode ? "Verify and sign in" : "Sign in"}
        </Button>
        {needsCode ? (
          <button type="button" className="text-sm text-primary hover:underline"
                  onClick={() => { setNeedsCode(false); setCode(""); setError(null); }}>
            Use a different account
          </button>
        ) : null}
      </form>

      {!needsCode ? (
        <div className="mt-8 rounded-xl border border-border bg-white p-4">
          <p className="text-xs font-semibold text-heading">Demo accounts</p>
          <p className="mt-0.5 text-xs text-muted-foreground">Synthetic data. The password is in the README.</p>
          <div className="mt-3 grid gap-1 sm:grid-cols-2">
            {DEMO_USERS.map((u) => (
              <button key={u.email} type="button" onClick={() => setEmail(u.email)} aria-pressed={email === u.email}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-ice aria-pressed:bg-ice">
                <Avatar name={u.name} size="xs" />
                <span className="min-w-0 text-xs leading-tight">
                  <span className="block truncate font-medium text-heading">{u.name}</span>
                  <span className="block text-muted-foreground">{u.role}</span>
                </span>
              </button>
            ))}
          </div>
          <div className="mt-3 border-t border-border pt-3"><ApiStatus /></div>
        </div>
      ) : null}
    </AuthLayout>
  );
}
