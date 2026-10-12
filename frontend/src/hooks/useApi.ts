/** Small data-fetching hooks. Deliberately minimal — no query library needed. */

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../api/client';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** Run `fetcher` on mount and whenever `deps` change. */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    // Guards against a slow earlier request overwriting a newer result.
    let active = true;
    setLoading(true);
    setError(null);

    fetcher()
      .then((result) => { if (active) setData(result); })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

/** Wrap a mutating call with pending/error state. */
export function useAction<Args extends unknown[], R>(
  action: (...args: Args) => Promise<R>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: Args): Promise<R | null> => {
      setPending(true);
      setError(null);
      try {
        return await action(...args);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
        return null;
      } finally {
        setPending(false);
      }
    },
    [action],
  );

  return { run, pending, error, clearError: () => setError(null) };
}

/** Poll `fetcher` while `active` is true. Used for in-flight workflows. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  active: boolean,
): AsyncState<T> {
  const state = useAsync(fetcher, []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(state.reload, intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs, state.reload]);
  return state;
}
