import { Activity } from 'lucide-react';
import Panel from '../components/Panel';

/**
 * Phase A placeholder: every field is explicitly unavailable. Nothing here is
 * simulated — the read-only API slice replaces these rows with measured values.
 */
const ROWS = [
  ['API ENDPOINT', 'NOT CONFIGURED'],
  ['REPOSITORIES TRACKED', 'UNAVAILABLE'],
  ['EVENTS RECEIVED', 'UNAVAILABLE'],
  ['LAST EVENT', 'UNAVAILABLE'],
] as const;

export default function Overview() {
  return (
    <div className="mx-auto max-w-[1100px]">
      <Panel title="System Status" code="SYS-0x00" icon={Activity} accent="#00FFFF" glow>
        <dl className="divide-y divide-zinc-800 font-mono text-[11px]">
          {ROWS.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0">
              <dt className="tracking-[0.14em] text-zinc-400">{label}</dt>
              <dd className="text-zinc-500">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 border-t border-zinc-800 pt-3 font-mono text-[10px] leading-relaxed text-zinc-500">
          No data source is wired yet. Values appear only when the backend reports them.
        </p>
      </Panel>
    </div>
  );
}
