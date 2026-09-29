"use client";

/**
 * The logged-in user, shared by every page in the app shell. Loaded once from /auth/me;
 * with no valid session the user is sent to /login. Roles here only choose what to show;
 * the API enforces every permission itself (BUILD_PLAN §9).
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { Loading } from "@/components/page";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

const SessionContext = createContext<Me | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api<Me>("/auth/me")
      .then(setMe)
      .catch(() => router.replace("/login"));
  }, [router]);

  if (!me) return <Loading label="Checking your session…" />;
  return <SessionContext.Provider value={me}>{children}</SessionContext.Provider>;
}

export function useMe(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useMe must be used inside SessionProvider");
  return me;
}
