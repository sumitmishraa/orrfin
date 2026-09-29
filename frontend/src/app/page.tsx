/**
 * Placeholder home page for the walking skeleton (BUILD_PLAN §11, M0).
 * Step 3 replaces it with the login page and the logged-in shell.
 */
import { ShieldCheck } from "lucide-react";

import { ApiStatus } from "@/components/api-status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="bg-navy text-white">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-2 px-6">
          <ShieldCheck className="size-5 text-cyan" aria-hidden />
          <span className="font-semibold tracking-tight">Orrfin</span>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 items-center justify-center px-6 py-16">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <CardTitle className="text-2xl font-semibold text-heading">Orrfin Control Gate</CardTitle>
            <CardDescription>
              Supplier invoices checked line by line against the ERP purchase order and goods
              receipt, then approved by a named person.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <ApiStatus />
            <p className="text-xs text-muted-foreground">
              Controlled prototype on synthetic data; draft-only; not production.
            </p>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
