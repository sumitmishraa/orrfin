"use client";

/**
 * Shows whether the Orrfin API answers GET /health (BUILD_PLAN §11, M0 walking skeleton).
 * Status is shown with an icon and a text label, never by colour alone (docs/BRAND.md).
 */
import { useEffect, useState } from "react";
import { CircleCheck, CircleX, LoaderCircle } from "lucide-react";

import { API_URL } from "@/lib/api";

type ApiState = "checking" | "ok" | "unreachable";

export function ApiStatus() {
  const [state, setState] = useState<ApiState>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/health`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((body: { status?: string }) => setState(body.status === "ok" ? "ok" : "unreachable"))
      .catch(() => {
        if (!controller.signal.aborted) setState("unreachable");
      });
    return () => controller.abort();
  }, []);

  if (state === "checking") {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        Checking API…
      </p>
    );
  }

  if (state === "ok") {
    return (
      <p className="flex items-center gap-2 text-sm font-medium text-success">
        <CircleCheck className="size-4" aria-hidden />
        API connected
      </p>
    );
  }

  return (
    <p className="flex items-center gap-2 text-sm font-medium text-error">
      <CircleX className="size-4" aria-hidden />
      API not reachable at {API_URL}
    </p>
  );
}
