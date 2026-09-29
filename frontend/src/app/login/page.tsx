"use client";

/**
 * Login page (BUILD_PLAN §3 Auth, PROMPTS Step 3): email + password, brand navy backdrop.
 * The demo accounts listed below are fictional and exist only in the local synthetic demo.
 */
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, ShieldCheck } from "lucide-react";

import { ApiStatus } from "@/components/api-status";
import { ErrorNotice } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { post } from "@/lib/api";

const DEMO_USERS = [
  { email: "riya.requester@demo.orrfin.ai", label: "Riya · Requester" },
  { email: "arjun.buyer@demo.orrfin.ai", label: "Arjun · Buyer" },
  { email: "neha.approver@demo.orrfin.ai", label: "Neha · Approver (manager)" },
  { email: "vikram.finance@demo.orrfin.ai", label: "Vikram · Finance" },
  { email: "anita.admin@demo.orrfin.ai", label: "Anita · Admin" },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", { email, password });
      router.replace("/inbox");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed.");
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-1 items-center justify-center overflow-hidden bg-navy px-4 py-12">
      <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-cyan-bloom blur-3xl" />
      <div className="relative w-full max-w-md">
        <div className="mb-6 flex items-center justify-center gap-2 text-white">
          <ShieldCheck className="size-7 text-cyan" aria-hidden />
          <span className="text-2xl font-semibold tracking-tight">Orrfin</span>
        </div>
        <div className="rounded-2xl border border-blue-dark bg-white p-6 shadow-xl">
          <h1 className="text-xl font-semibold text-heading">Sign in to the Control Gate</h1>
          <p className="mt-1 text-sm text-muted-foreground">Requests, approvals and invoice checks in one place.</p>

          <form onSubmit={onSubmit} className="mt-5 flex flex-col gap-4">
            <Field label="Work email" htmlFor="email">
              <Input id="email" type="email" autoComplete="username" required value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <ErrorNotice message={error} />
            <Button type="submit" size="lg" disabled={busy} className="w-full">
              {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
              Sign in
            </Button>
          </form>

          <div className="mt-6 border-t border-border pt-4">
            <p className="text-xs font-medium text-heading">Demo accounts (synthetic data; password in the README)</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {DEMO_USERS.map((u) => (
                <button key={u.email} type="button" onClick={() => setEmail(u.email)}
                        className="rounded-full border border-border bg-ice-light px-2.5 py-1 text-xs text-heading hover:bg-ice">
                  {u.label}
                </button>
              ))}
            </div>
            <div className="mt-4"><ApiStatus /></div>
          </div>
        </div>
        <p className="mt-4 text-center text-xs text-cyan/80">
          Controlled prototype on synthetic data; draft-only; not production.
        </p>
      </div>
    </div>
  );
}
