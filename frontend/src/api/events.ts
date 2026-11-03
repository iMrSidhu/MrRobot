import { API_BASE, ApiError } from './client';
import { isRecord } from './legacy';

/** One row of the backend event log, already normalised for display. */
export type SentinelEvent = {
  id: number;
  repoId: number | null;
  type: string;
  message: string;
  payload: Record<string, unknown>;
  timestamp: string;
};

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'offline';

/** Event types whose arrival changes what a dossier shows (integration design §3). */
export const REFRESH_EVENT_TYPES: ReadonlySet<string> = new Set([
  'SYNTHESIS_DONE',
  'SECURITY_DONE',
  'REPORTED',
  'FAILED_AUDIT',
  'ERROR',
  'RECLAIMED',
]);

/**
 * Parses one SSE frame. Exported for tests; malformed frames are dropped rather
 * than rendered as blank rows.
 */
export function parseSseFrame(frame: string): SentinelEvent | null {
  let id: number | null = null;
  let frameType = '';
  let data = '';

  for (const line of frame.split('\n')) {
    if (line.startsWith('id:')) id = Number(line.slice(3).trim());
    else if (line.startsWith('event:')) frameType = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }

  if (id === null || !Number.isInteger(id) || data === '') return null;

  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(payload)) return null;

  return {
    id,
    repoId: typeof payload.repo_id === 'number' ? payload.repo_id : null,
    type: typeof payload.type === 'string' && payload.type !== '' ? payload.type : frameType || 'UNKNOWN',
    message: typeof payload.message === 'string' ? payload.message : '',
    payload: isRecord(payload.payload) ? payload.payload : {},
    timestamp: typeof payload.timestamp === 'string' ? payload.timestamp : '',
  };
}

type StreamOptions = {
  /** Last event id already seen; the server replays everything after it. */
  afterId: number;
  signal: AbortSignal;
  onOpen: () => void;
  onEvent: (event: SentinelEvent) => void;
};

/**
 * Reads `/events/stream` with fetch rather than EventSource: the browser's
 * EventSource cannot send the `last-event-id` header on a fresh connection.
 */
export async function streamEvents({ afterId, signal, onOpen, onEvent }: StreamOptions): Promise<void> {
  const headers: Record<string, string> = { accept: 'text/event-stream' };
  if (afterId > 0) headers['last-event-id'] = String(afterId);

  const response = await fetch(`${API_BASE}/events/stream`, { signal, headers });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, `Event stream failed: ${response.status} ${response.statusText}`);
  }

  onOpen();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    let split = buffer.indexOf('\n\n');
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const event = parseSseFrame(frame);
      if (event) onEvent(event);
      split = buffer.indexOf('\n\n');
    }
  }
}
