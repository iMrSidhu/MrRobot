import { Activity, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { fetchHealth, fetchRepos } from '../api/client';
import Panel from '../components/Panel';
import { useResource } from '../hooks/useResource';

const STATUS_ORDER = ['DONE', 'FAILED_AUDIT', 'ANALYZING', 'ANALYZED', 'PROCESSED', 'CLONING', 'QUEUED'];

export default function Overview() {
  const [nonce, setNonce] = useState(0);

  const health = useResource(`health:${nonce}`, fetchHealth);
  const repos = useResource(`repos:${nonce}`, fetchRepos);

  const reachable = health.status === 'ready' && health.data.status === 'ok';
  const apiLabel =
    health.status === 'loading'
      ? 'CHECKING…'
      : reachable
        ? 'REACHABLE'
        : `UNREACHABLE${health.status === 'error' ? ` — ${health.error}` : ''}`;

  const rows: Array<[string, string]> = [
    ['API ENDPOINT', apiLabel],
    [
      'REPOSITORIES TRACKED',
      repos.status === 'ready' ? `${repos.data.length} (system-wide)` : repos.status === 'loading' ? 'LOADING…' : 'UNAVAILABLE',
    ],
    [
      'LAST REPOSITORY UPDATE',
      repos.status === 'ready' && repos.data.length > 0
        ? (repos.data.at(-1)?.timestamp ?? 'UNKNOWN')
        : 'NONE',
    ],
    ['EVENTS RECEIVED', 'UNAVAILABLE'],
  ];

  const counts = new Map<string, number>();
  if (repos.status === 'ready') {
    for (const repo of repos.data) counts.set(repo.status, (counts.get(repo.status) ?? 0) + 1);
  }
  const statusLine = STATUS_ORDER.filter((status) => counts.has(status))
    .map((status) => `${status} ${counts.get(status)}`)
    .join(' · ');

  const error = health.status === 'error' ? health.error : repos.status === 'error' ? repos.error : null;

  return (
    <div className="mx-auto max-w-[1100px] space-y-4">
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
          <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] tracking-[0.12em] text-cy">
            {statusLine}
          </p>
        )}

        {error && (
          <p role="alert" className="mt-3 border-t border-crim/50 pt-3 font-mono text-[10px] text-crim">
            {error}
          </p>
        )}

        <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] leading-relaxed text-zinc-500">
          Counts are system-wide and come from the read-only API. Nothing here is simulated.
        </p>
      </Panel>
    </div>
  );
}
