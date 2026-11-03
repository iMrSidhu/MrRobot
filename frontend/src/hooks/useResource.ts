import { useEffect, useRef, useState } from 'react';

export type ResourceState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'ready'; data: T; error: null }
  | { status: 'error'; data: null; error: string };

/**
 * One remote resource keyed by `key`.
 *
 * Two guards the design calls for (§8): the effect aborts the previous request, and a
 * `current` flag drops anything that resolves after cleanup. Switching selection during
 * a slow fetch therefore cannot let the late response overwrite the newer one.
 */
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
): ResourceState<T> {
  const loadRef = useRef(load);
  loadRef.current = load;

  const [state, setState] = useState<ResourceState<T>>({ status: 'loading', data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    let current = true;

    setState({ status: 'loading', data: null, error: null });

    loadRef.current(controller.signal).then(
      (data) => {
        if (current) setState({ status: 'ready', data, error: null });
      },
      (error: unknown) => {
        if (!current || controller.signal.aborted) return;
        setState({
          status: 'error',
          data: null,
          error: error instanceof Error ? error.message : String(error),
        });
      },
    );

    return () => {
      current = false;
      controller.abort();
    };
  }, [key]);

  return state;
}
