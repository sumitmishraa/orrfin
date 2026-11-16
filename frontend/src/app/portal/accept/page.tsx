"use client";

/**
 * Supplier portal: use an invitation link to choose a password (BUILD_PLAN §9 v3.0).
 * The link works once and for 7 days; the server decides, this page only reports the answer.
 */
import { useState, type FormEvent } from "react";
import Link from "next/link";

import { ErrorNotice } from "@/components/page";
import { AuthLayout } from "@/components/shell/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { portalApi } from "@/lib/portal-api";

const SUPPLIER_POINTS = [
  "Enter your company, tax and bank details once, and upload your documents.",
  "Your customer's finance team reviews them; you see what is still missing.",
  "Answer requests for quotation from the same place, sealed until the deadline.",
];

export default function AcceptInvitePage() {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 12) return setError("Choose a password of at least 12 characters.");
    if (password !== again) return setError("The two passwords are not the same.");
    // Read at submit time, so the token never sits in React state or gets rendered.
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    setBusy(true);
    setError(null);
    try {
      await portalApi("/portal/invites/accept", { method: "POST", body: JSON.stringify({ token, password }) });
      window.history.replaceState(null, "", "/portal/accept"); // drop the used token from the address bar
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout headline="Get set up as a supplier." points={SUPPLIER_POINTS}>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-heading">Supplier portal</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">Choose a password to finish setting up your access.</p>
      </div>
      {done ? (
        <div className="space-y-3 rounded-xl border border-border bg-white p-5 shadow-raised">
          <p className="text-sm">Your password is set.</p>
          <Link href="/portal" className="text-sm font-medium text-primary underline">Sign in to the portal</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-border bg-white p-5 shadow-raised">
          <ErrorNotice message={error} />
          <Field label="New password" htmlFor="password" hint="At least 12 characters.">
            <Input id="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Field label="Type it again" htmlFor="again">
            <Input id="again" type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} />
          </Field>
          <Button type="submit" size="lg" disabled={busy} className="h-10 w-full">Set password</Button>
        </form>
      )}
    </AuthLayout>
  );
}
