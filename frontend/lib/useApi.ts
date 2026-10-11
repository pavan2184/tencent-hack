import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "./apiClient";

export interface QueryState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads data for `key`; a new key refetches and drops the previous key's data.
 * `null` skips loading. `reload()` refetches while keeping current data visible.
 */
export function useApiQuery<T>(
  key: string | null,
  load: () => Promise<T>,
): QueryState<T> {
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<{
    key: string | null;
    nonce: number;
    data?: T;
    error: ApiError | null;
  }>({ key: null, nonce: -1, error: null });

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    loadRef.current().then(
      (data) => {
        if (!cancelled) setState({ key, nonce, data, error: null });
      },
      (error: unknown) => {
        if (!cancelled) setState({ key, nonce, error: toApiError(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const settled = state.key === key && state.nonce === nonce;

  return {
    data: state.key === key ? state.data : undefined,
    error: settled ? state.error : null,
    loading: key !== null && !settled,
    reload,
  };
}

export type ActionResult<R> =
  { ok: true; data: R } | { ok: false; error: ApiError };

/** Wraps a mutation with pending/error/data state. */
export function useApiAction<Args extends unknown[], R>(
  action: (...args: Args) => Promise<R>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [data, setData] = useState<R | undefined>(undefined);

  async function run(...args: Args): Promise<ActionResult<R>> {
    setPending(true);
    setError(null);
    try {
      const result = await action(...args);
      setData(() => result);
      return { ok: true, data: result };
    } catch (err) {
      const apiError = toApiError(err);
      setError(apiError);
      return { ok: false, error: apiError };
    } finally {
      setPending(false);
    }
  }

  return { run, pending, error, data };
}
