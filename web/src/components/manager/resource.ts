"use client";

import { useEffect, useState } from "react";

/** Abort stale filter requests and never label previous results with new filters. */
export function useManagerResource<T>(key: string, load: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key: "", data: null, error: null });
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ key, data, error: null }); },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ key, data: null, error: error instanceof Error ? error.message : "Unable to load analysis" });
      },
    );
    return () => controller.abort();
  }, [key, load]);
  return state.key === key ? { ...state, loading: false } : { data: null, error: null, loading: true };
}
