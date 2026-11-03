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
  const ready = repos.status === 'ready';

  const tiles: Array<{ label: string; value: string; tone: string }> = [
    { label: 'REPOSITORIES', value: ready ? String(repos.data.length) : '—', tone: 'text-zinc-100' },
    { label: 'COMPLETED', value: ready ? String(count('DONE')) : '—', tone: 'text-cy' },
    { label: 'FAILED', value: ready ? String(count('FAILED_AUDIT')) : '—', tone: 'text-crim' },
    { label: 'EVENTS', value: String(live.events.length), tone: 'text-neon' },
  ];

  const counts = new Map<string, number>();
  if (ready) {
    for (const repo of repos.data) counts.set(repo.status, (counts.get(repo.status) ?? 0) + 1);
  }
  const segments = STATUS_ORDER.filter((status) => counts.has(status)).map((status) => ({
    status,
    count: counts.get(status) ?? 0,
  }));
  const total = ready ? repos.data.length : 0;

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
        <div className="grid grid-cols-2 gap-2">
          {tiles.map((tile) => (
            <div key={tile.label} className="chamfer-sm border border-zinc-800 bg-void/60 px-3 py-2">
              <div className="font-mono text-[9px] tracking-[0.16em] text-zinc-500">{tile.label}</div>
              <div className={`font-mono text-2xl leading-tight ${tile.tone}`}>{tile.value}</div>
            </div>
          ))}
        </div>

        {total > 0 && (
          <div className="mt-3 space-y-1">
            <div className="chamfer-xs flex h-2.5 overflow-hidden border border-zinc-800" role="img" aria-label={segments.map((s) => `${s.status} ${s.count}`).join(', ')}>
              {segments.map((segment) => (
                <div
                  key={segment.status}
                  title={`${segment.status} ${segment.count}`}
                  className={
                    segment.status === 'DONE'
                      ? 'bg-cy'
                      : segment.status === 'FAILED_AUDIT'
                        ? 'bg-crim'
                        : segment.status === 'QUEUED'
                          ? 'bg-zinc-700'
                          : 'bg-neon'
                  }
                  style={{ width: `${(segment.count / total) * 100}%` }}
                />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-3 font-mono text-[9px] text-zinc-500">
              {segments.map((segment) => (
                <span key={segment.status}>
                  {segment.status} {segment.count}
                </span>
              ))}
            </div>
          </div>
        )}

        {repos.status === 'error' && (
          <p role="alert" className="mt-3 border-t border-crim/50 pt-2 font-mono text-[10px] text-crim">
            {repos.error}
          </p>
        )}
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

        <p className="mt-3 border-t border-zinc-800 pt-2 font-mono text-[9px] text-zinc-600">
          Last {FEED_LIMIT} of {live.events.length} · replays from last id on reconnect
        </p>
      </Panel>
    </div>
  );
}
