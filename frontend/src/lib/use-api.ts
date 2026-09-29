"use client";

/**
 * Load one API resource in a client component, with loading/error state and a reload()
 * to call after an action changes it. Pass null to skip loading.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const reload = useCallback(async () => {
    if (path === null) return;
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load data.");
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    // Fetching on mount is the point of this hook; state updates happen after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
  }, [reload]);

  return { data, setData, error, loading, reload };
}
