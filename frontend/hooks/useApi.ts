"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";

interface State<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Minimal data-fetching hook.
 *
 * Deliberately dependency-free: the dashboard has a handful of endpoints and
 * pulling in a caching library would be more machinery than this needs.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList = [],
): State<T> & { refetch: () => void } {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({ ...previous, loading: true, error: null }));

    fetcher()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : "Unexpected error";
        setState({ data: null, error: message, loading: false });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { ...state, refetch };
}

/** Wrap an async action with pending/error state, for buttons. */
export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      setPending(true);
      setError(null);
      try {
        return await action(...args);
      } catch (caught: unknown) {
        setError(
          caught instanceof ApiError
            ? caught.message
            : caught instanceof Error
              ? caught.message
              : "Unexpected error",
        );
        return null;
      } finally {
        setPending(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return { run, pending, error, clearError: () => setError(null) };
}
