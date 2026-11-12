"use client";

/**
 * Layout for every logged-in page: loads the session once (useMe), then draws the app shell
 * around the page. Navigation lives in lib/navigation.ts; the shell in components/shell/.
 */
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/app-shell";
import { SessionProvider } from "@/components/session";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
