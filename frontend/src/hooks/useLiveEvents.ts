import { useEffect, useRef, useState } from 'react';
import { streamEvents } from '../api/events';
import type { SentinelEvent, StreamStatus } from '../api/events';

/** Feed is bounded: only the most recent events stay in memory. */
const MAX_EVENTS = 100;
const MAX_BACKOFF_MS = 15000;
/** After this many failed attempts the badge stops pretending it is about to recover. */
const OFFLINE_AFTER_ATTEMPTS = 5;

export type LiveEvents = {
  status: StreamStatus;
  events: SentinelEvent[];
  attempts: number;
  retry: () => void;
};

/**
 * Owns the single SSE connection for the app. Reconnects with exponential
 * backoff, resumes from the last seen id, and drops duplicate replays.
 */
export function useLiveEvents(): LiveEvents {
  const [state, setState] = useState<{ status: StreamStatus; events: SentinelEvent[]; attempts: number }>({
    status: 'connecting',
    events: [],
    attempts: 0,
  });
  const lastId = useRef(0);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let controller: AbortController | null = null;
    let timer: number | undefined;

    const connect = async () => {
      controller = new AbortController();
      try {
        await streamEvents({
          afterId: lastId.current,
          signal: controller.signal,
          onOpen: () => {
            failures = 0;
            setState((prev) => ({ ...prev, status: 'live', attempts: 0 }));
          },
          onEvent: (event) => {
            if (event.id <= lastId.current) return;
            lastId.current = event.id;
            setState((prev) => ({
              status: 'live',
              attempts: 0,
              events: [...prev.events, event].slice(-MAX_EVENTS),
            }));
          },
        });
      } catch {
        // Aborting on unmount is normal; anything else falls through to retry.
      }
      if (cancelled) return;

      failures += 1;
      setState((prev) => ({
        ...prev,
        status: failures >= OFFLINE_AFTER_ATTEMPTS ? 'offline' : 'reconnecting',
        attempts: failures,
      }));
      timer = window.setTimeout(() => void connect(), Math.min(1000 * 2 ** (failures - 1), MAX_BACKOFF_MS));
    };

    void connect();

    return () => {
      cancelled = true;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [nonce]);

  return {
    ...state,
    retry: () => {
      setState((prev) => ({ ...prev, status: 'connecting', attempts: 0 }));
      setNonce((value) => value + 1);
    },
  };
}
