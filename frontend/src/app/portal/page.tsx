"use client";

/**
 * Supplier portal home (BUILD_PLAN change 41, §9 v3.0): sign in, then fill in company details,
 * bank details and documents, and send them for review.
 *
 * This page lives outside the employee app shell and uses its own session cookie. The server
 * returns only the signed-in supplier's own record; there is no supplier id anywhere in the
 * requests, so there is nothing to change to reach another supplier.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ShieldCheck } from "lucide-react";

import { ErrorNotice, Loading, Panel } from "@/components/page";
import { AuthLayout } from "@/components/shell/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { PortalAuthError, portalApi, portalUpload } from "@/lib/portal-api";

import { PortalRfqs } from "./rfqs";

const SUPPLIER_POINTS = [
  "Enter your company, tax and bank details once, and upload your documents.",
  "Your customer's finance team reviews them; you see what is still missing.",
  "Answer requests for quotation from the same place, sealed until the deadline.",
];

interface PortalView {
  contact_name: string; legal_name: string; country: "IN" | "AE"; status: string; tax_id: string | null; pan: string | null;
  answers: Record<string, string>; questions: Record<string, string>; bank_last4: string | null;
  review_reason: string | null; editable: boolean; to_do: string[];
  documents: { id: string; kind: string; filename: string; expires_on: string | null }[];
}

const STATUS_TEXT: Record<string, string> = {
  invited: "Please fill in your details and send them for review.",
  rejected: "Your details were sent back. Please correct them and send them again.",
  submitted: "Your details are with the reviewer. You will hear from your contact.",
  approved: "Your details are approved. Your customer is setting you up in their accounting system.",
  handed_over: "Your details are approved. Your customer is setting you up in their accounting system.",
  active: "You are set up as a supplier.",
};
const DOCUMENT_KINDS = [
  ["tax_certificate", "Tax registration certificate"], ["pan", "PAN card"], ["bank_proof", "Bank proof (cancelled cheque or bank letter)"], ["other", "Other"],
];

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await portalApi("/portal/login", { method: "POST", body: JSON.stringify({ email, password }) });
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-6 space-y-4">
      <ErrorNotice message={error} />
      <Field label="Email" htmlFor="portal-email">
        <Input id="portal-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password" htmlFor="portal-password">
        <Input id="portal-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Button type="submit" size="lg" disabled={busy} className="h-10 w-full">Sign in</Button>
    </form>
  );
}

export default function SupplierPortalPage() {
  const [view, setView] = useState<PortalView | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState({ tax_id: "", pan: "", answers: {} as Record<string, string> });
  const [bank, setBank] = useState({ account_name: "", account_number: "", ifsc: "" });
  const [upload, setUpload] = useState<{ kind: string; expires_on: string; file: File | null }>({ kind: "tax_certificate", expires_on: "", file: null });

  const show = useCallback((next: PortalView) => {
    setView(next);
    setProfile({ tax_id: next.tax_id ?? "", pan: next.pan ?? "", answers: next.answers ?? {} });
  }, []);

  const load = useCallback(async () => {
    try {
      show(await portalApi<PortalView>("/portal/me"));
      setSignedOut(false);
    } catch (err) {
      if (err instanceof PortalAuthError) setSignedOut(true);
      else setError(err instanceof Error ? err.message : "Could not load your details.");
    }
  }, [show]);

  useEffect(() => {
    // Loading on mount is the point; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function run(action: () => Promise<PortalView | void>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      if (next) show(next);
    } catch (err) {
      if (err instanceof PortalAuthError) setSignedOut(true);
      else setError(err instanceof Error ? err.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const india = view?.country === "IN";
  const saveProfile = () => run(() => portalApi<PortalView>("/portal/profile", {
    method: "PUT", body: JSON.stringify({ tax_id: profile.tax_id, pan: india ? profile.pan : null, answers: profile.answers }) }));
  const saveBank = () => run(async () => {
    const next = await portalApi<PortalView>("/portal/bank", {
      method: "PUT", body: JSON.stringify({ ...bank, ifsc: india ? bank.ifsc : null }) });
    setBank({ account_name: "", account_number: "", ifsc: "" }); // do not keep the number on screen
    return next;
  });
  const addDocument = () => run(async () => {
    if (!upload.file) return;
    const next = await portalUpload<PortalView>("/portal/documents", upload.file, { kind: upload.kind, expires_on: upload.expires_on });
    setUpload({ kind: upload.kind, expires_on: "", file: null });
    return next;
  });
  const signOut = () => run(async () => {
    await portalApi("/portal/logout", { method: "POST" });
    setView(null);
    setSignedOut(true);
  });

  if (signedOut) {
    return (
      <AuthLayout headline="Get set up as a supplier." points={SUPPLIER_POINTS}>
        <h1 className="text-2xl font-semibold tracking-tight text-heading">Supplier sign in</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">Use the email your customer invited. No account yet? Open the invitation link they sent.</p>
        <div className="mt-4"><ErrorNotice message={error} /></div>
        <SignIn onSignedIn={load} />
      </AuthLayout>
    );
  }

  return (
    <div className="min-h-screen flex-1 bg-ice-light">
      <header className="bg-navy text-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between gap-3 px-4">
          <span className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-blue-dark ring-1 ring-white/10">
              <ShieldCheck className="size-[18px] text-cyan" aria-hidden />
            </span>
            <span className="font-semibold tracking-tight">Orrfin</span>
            <span className="hidden text-sm text-white/55 sm:inline">· Supplier portal</span>
          </span>
          {view ? (
            <span className="flex items-center gap-3">
              <span className="hidden text-right text-xs leading-tight text-white/70 sm:block">
                <span className="block font-medium text-white">{view.legal_name}</span>{view.contact_name}
              </span>
              <Button variant="outline" size="sm" onClick={signOut} disabled={busy}
                      className="border-white/20 bg-transparent text-white hover:bg-white/10 hover:text-white">Sign out</Button>
            </span>
          ) : null}
        </div>
      </header>
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <ErrorNotice message={error} />

      {!view ? <Loading /> : (
        <>
          <div role="status" className="rounded-xl border border-border bg-white p-4 text-sm shadow-raised">
            <p className="font-medium text-heading">{STATUS_TEXT[view.status] ?? view.status}</p>
            {view.review_reason ? <p className="mt-1">Reviewer&apos;s note: {view.review_reason}</p> : null}
            {view.editable && view.to_do.length > 0 ? (
              <ul className="mt-2 list-disc pl-5">{view.to_do.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : null}
          </div>

          <Panel title="1. Company details">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={india ? "GSTIN" : "TRN"} htmlFor="tax-id">
                <Input id="tax-id" disabled={!view.editable} value={profile.tax_id} onChange={(e) => setProfile({ ...profile, tax_id: e.target.value.toUpperCase() })} />
              </Field>
              {india ? (
                <Field label="Company PAN" htmlFor="pan">
                  <Input id="pan" disabled={!view.editable} value={profile.pan} onChange={(e) => setProfile({ ...profile, pan: e.target.value.toUpperCase() })} />
                </Field>
              ) : null}
              {Object.entries(view.questions).map(([key, question]) => (
                <Field key={key} label={question} htmlFor={`q-${key}`} className="sm:col-span-2">
                  <Select id={`q-${key}`} disabled={!view.editable} value={profile.answers[key] ?? ""}
                          onChange={(e) => setProfile({ ...profile, answers: { ...profile.answers, [key]: e.target.value } })}>
                    <option value="">Choose…</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </Select>
                </Field>
              ))}
              {view.editable ? <div><Button onClick={saveProfile} disabled={busy}>Save details</Button></div> : null}
            </div>
          </Panel>

          <Panel title="2. Bank details">
            <div className="grid gap-3 sm:grid-cols-2">
              <p className="text-sm text-muted-foreground sm:col-span-2">
                {view.bank_last4 ? `On file: account ending ${view.bank_last4}. ` : "No bank details yet. "}
                The full number is stored encrypted and is never shown again. Changing it later sends your details back for review.
              </p>
              <Field label="Account holder" htmlFor="bank-name">
                <Input id="bank-name" autoComplete="off" value={bank.account_name} onChange={(e) => setBank({ ...bank, account_name: e.target.value })} />
              </Field>
              <Field label={india ? "Account number" : "IBAN"} htmlFor="bank-number">
                <Input id="bank-number" autoComplete="off" value={bank.account_number} onChange={(e) => setBank({ ...bank, account_number: e.target.value })} />
              </Field>
              {india ? (
                <Field label="IFSC" htmlFor="bank-ifsc">
                  <Input id="bank-ifsc" autoComplete="off" value={bank.ifsc} onChange={(e) => setBank({ ...bank, ifsc: e.target.value.toUpperCase() })} />
                </Field>
              ) : null}
              <div className="sm:col-span-2"><Button onClick={saveBank} disabled={busy || !bank.account_name || !bank.account_number}>Save bank details</Button></div>
            </div>
          </Panel>

          <Panel title="3. Documents">
            <div className="space-y-4">
              {view.documents.length > 0 ? (
                <ul className="space-y-1 text-sm">
                  {view.documents.map((d) => (
                    <li key={d.id}>{DOCUMENT_KINDS.find(([k]) => k === d.kind)?.[1] ?? d.kind}: {d.filename}{d.expires_on ? ` (valid until ${d.expires_on})` : ""}</li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-foreground">Nothing uploaded yet.</p>}
              <div className="grid items-end gap-3 sm:grid-cols-3">
                <Field label="Document" htmlFor="doc-kind">
                  <Select id="doc-kind" value={upload.kind} onChange={(e) => setUpload({ ...upload, kind: e.target.value })}>
                    {DOCUMENT_KINDS.filter(([k]) => india || k !== "pan").map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </Select>
                </Field>
                <Field label="Valid until (if it expires)" htmlFor="doc-expiry">
                  <Input id="doc-expiry" type="date" value={upload.expires_on} onChange={(e) => setUpload({ ...upload, expires_on: e.target.value })} />
                </Field>
                <Field label="File (PDF, JPEG or PNG, up to 10 MB)" htmlFor="doc-file">
                  <input id="doc-file" type="file" accept="application/pdf,image/jpeg,image/png" className="text-sm"
                         onChange={(e) => setUpload({ ...upload, file: e.target.files?.[0] ?? null })} />
                </Field>
              </div>
              <Button variant="outline" onClick={addDocument} disabled={busy || !upload.file}>Upload document</Button>
            </div>
          </Panel>

          {["approved", "handed_over", "active"].includes(view.status) ? <PortalRfqs /> : null}

          {view.editable ? (
            <div className="flex items-center gap-3">
              <Button onClick={() => run(() => portalApi<PortalView>("/portal/submit", { method: "POST" }))} disabled={busy}>Send for review</Button>
              <p className="text-sm text-muted-foreground">You cannot change your company details while they are being reviewed.</p>
            </div>
          ) : null}
        </>
      )}
    </main>
    </div>
  );
}
