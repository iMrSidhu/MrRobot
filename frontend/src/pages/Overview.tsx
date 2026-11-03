import { Activity, Radio, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { fetchRepos } from '../api/client';
import type { SentinelEvent } from '../api/events';
import Panel from '../components/Panel';
import type { LiveEvents } from '../hooks/useLiveEvents';
import { useResource } from '../hooks/useResource';

const STATUS_ORDER = ['DONE', 'FAILED_AUDIT', 'ANALYZING', 'ANALYZED', 'PROCESSED', 'CLONING', 'QUEUED'];
const FEED_LIMIT = 12;

const TYPE_TONE: Record<string, string> = {
  ERROR: 'text-crim',
  FAILED_AUDIT: 'text-crim',
  RATE_LIMIT: 'text-neon',
  REPORTED: 'text-cy',
  SECURITY_DONE: 'text-cy',
};

const STATUS_LABEL: Record<LiveEvents['status'], string> = {
  connecting: 'CONNECTING',
  live: 'LIVE',
  reconnecting: 'RECONNECTING',
  offline: 'OFFLINE',
};

function eventTime(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleTimeString('en-GB', { hour12: false });
}

function EventRow({ event }: { event: SentinelEvent }) {
  return (
    <li className="flex items-start gap-2 border-b border-zinc-900 py-1.5 last:border-b-0">
      <time dateTime={event.timestamp} title={event.timestamp} className="shrink-0 font-mono text-[10px] text-zinc-500">
        {eventTime(event.timestamp)}
      </time>
      <span className={`w-[104px] shrink-0 font-mono text-[9px] tracking-[0.1em] ${TYPE_TONE[event.type] ?? 'text-zinc-400'}`}>
        {event.type}
      </span>
      <span className="min-w-0 flex-1 break-words font-mono text-[10px] leading-relaxed text-zinc-300">
        {event.message || '—'}
      </span>
      <span className="shrink-0 font-mono text-[9px] text-zinc-600">{event.repoId ?? '—'}</span>
    </li>
  );
}

export default function Overview({ live }: { live: LiveEvents }) {
  const [nonce, setNonce] = useState(0);
  const repos = useResource(`repos:${nonce}`, fetchRepos);

  const count = (status: string) => (repos.status === 'ready' ? repos.data.filter((repo) => repo.status === status).length : 0);

  const rows: Array<[string, string]> = [
    [
      'REPOSITORIES TRACKED',
      repos.status === 'ready' ? `${repos.data.length} (system-wide)` : repos.status === 'loading' ? 'LOADING…' : 'UNAVAILABLE',
    ],
    ['COMPLETED', repos.status === 'ready' ? String(count('DONE')) : 'UNAVAILABLE'],
    ['FAILED AUDIT', repos.status === 'ready' ? String(count('FAILED_AUDIT')) : 'UNAVAILABLE'],
    [
      'LAST REPOSITORY UPDATE',
      repos.status === 'ready' && repos.data.length > 0 ? (repos.data.at(-1)?.timestamp ?? 'UNKNOWN') : 'NONE',
    ],
    ['EVENTS OBSERVED', `${live.events.length} (this session)`],
  ];

  const counts = new Map<string, number>();
  if (repos.status === 'ready') {
    for (const repo of repos.data) counts.set(repo.status, (counts.get(repo.status) ?? 0) + 1);
  }
  const statusLine = STATUS_ORDER.filter((status) => counts.has(status))
    .map((status) => `${status} ${counts.get(status)}`)
    .join(' · ');

  const feed = live.events.slice(-FEED_LIMIT).reverse();
  const stale = live.status !== 'live';

  return (
    <div className="mx-auto grid max-w-[1200px] gap-4 xl:grid-cols-2">
      <Panel
        title="System Status"
        code="SYS-0x00"
        icon={Activity}
        accent="#00FFFF"
        glow
        action={
          <button
            type="button"
            onClick={() => setNonce((value) => value + 1)}
            className="flex items-center gap-1.5 chamfer-xs border border-zinc-700 px-2 py-1 font-mono text-[10px] tracking-[0.14em] text-zinc-300 hover:border-cy hover:text-cy"
          >
            <RefreshCw size={11} aria-hidden="true" />
            RESCAN
          </button>
        }
      >
        <dl className="divide-y divide-zinc-800 font-mono text-[11px]">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-4 py-2 first:pt-0 last:pb-0">
              <dt className="shrink-0 tracking-[0.14em] text-zinc-400">{label}</dt>
              <dd className="break-all text-right text-zinc-300">{value}</dd>
            </div>
          ))}
        </dl>

        {statusLine && (
          <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] tracking-[0.12em] text-cy">{statusLine}</p>
        )}

        {repos.status === 'error' && (
          <p role="alert" className="mt-3 border-t border-crim/50 pt-3 font-mono text-[10px] text-crim">
            {repos.error}
          </p>
        )}

        <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] leading-relaxed text-zinc-500">
          Counts are repository-scoped and system-wide. Values come from the read-only API; nothing here is simulated.
        </p>
      </Panel>

      <Panel
        title="Live Event Feed"
        code="EVT-STREAM"
        icon={Radio}
        accent="#FCE205"
        action={
          <div className="flex items-center gap-2">
            <span
              className={`flex items-center gap-1.5 font-mono text-[9px] tracking-[0.14em] ${
                live.status === 'live'
                  ? 'text-cy'
                  : live.status === 'offline'
                    ? 'text-crim'
                    : live.status === 'reconnecting'
                      ? 'text-neon'
                      : 'text-zinc-400'
              }`}
            >
              <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 rounded-full ${
                  live.status === 'live' ? 'pulse-dot bg-cy' : live.status === 'offline' ? 'bg-crim' : 'bg-zinc-500'
                }`}
              />
              {STATUS_LABEL[live.status]}
              {live.status === 'reconnecting' && ` ${live.attempts}`}
            </span>
            {live.status === 'offline' && (
              <button
                type="button"
                onClick={live.retry}
                className="chamfer-xs border border-zinc-700 px-2 py-0.5 font-mono text-[9px] tracking-[0.14em] text-zinc-300 hover:border-cy hover:text-cy"
              >
                RETRY
              </button>
            )}
          </div>
        }
      >
        {stale && (
          <p role="status" className="mb-2 border border-neon/40 px-2 py-1 font-mono text-[9px] leading-relaxed text-neon">
            Stream {live.status === 'offline' ? 'stopped' : 'paused'} — this feed and any dossier opened from it may be out of date.
          </p>
        )}

        {feed.length === 0 ? (
          <p className="font-mono text-[10px] text-zinc-500">
            {live.status === 'connecting' ? 'Waiting for the event stream…' : 'No events received yet.'}
          </p>
        ) : (
          <ul aria-live="polite" aria-relevant="additions" className="max-h-[46vh] overflow-y-auto">
            {feed.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </ul>
        )}

        <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] leading-relaxed text-zinc-500">
          Newest first, last {FEED_LIMIT} of {live.events.length} observed. History replays on reconnect from the last event id.
        </p>
      </Panel>
    </div>
  );
}
