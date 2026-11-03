import { useState } from 'react';
import {
  Activity,
  Gauge,
  GitPullRequest,
  History,
  Menu as MenuIcon,
  PackageCheck,
  Plug,
  Radar,
  ShieldCheck,
  X,
} from 'lucide-react';
import { fetchHealth } from '../api/client';
import { useClock } from '../hooks/useClock';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useResource } from '../hooks/useResource';
import Overview from '../pages/Overview';
import Repository from '../pages/Repository';
import { useParam } from '../state/url';

type TabId = 'overview' | 'repository' | 'adoption' | 'contribution' | 'integration' | 'changes';

type NavItem = {
  id: TabId;
  label: string;
  code: string;
  icon: typeof Gauge;
  /** A tab is only navigable once its backend resource exists (integration design §7). */
  enabled: boolean;
};

const NAV: readonly NavItem[] = [
  { id: 'overview', label: 'Overview', code: '01', icon: Gauge, enabled: true },
  { id: 'repository', label: 'Repository', code: '02', icon: Radar, enabled: true },
  { id: 'adoption', label: 'Adoption', code: '03', icon: PackageCheck, enabled: false },
  { id: 'contribution', label: 'Contribution', code: '04', icon: GitPullRequest, enabled: false },
  { id: 'integration', label: 'Integration', code: '05', icon: Plug, enabled: false },
  { id: 'changes', label: 'Changes', code: '06', icon: History, enabled: false },
];

const TAB_IDS = NAV.filter((item) => item.enabled).map((item) => item.id);

function isTabId(value: string | null): value is TabId {
  return value !== null && (TAB_IDS as string[]).includes(value);
}

export default function Shell() {
  const [view, setView] = useParam('view');
  const [navOpen, setNavOpen] = useState(false);
  const now = useClock();
  /** Re-checks reachability whenever the stream retries, so the badge cannot claim "reachable" while the API is dead. */
  const live = useLiveEvents();
  const health = useResource(`health:${live.attempts}`, fetchHealth);

  const tab: TabId = isTabId(view) ? view : 'overview';
  const apiState = health.status === 'loading' ? 'CHECKING' : health.status === 'ready' ? 'REACHABLE' : 'OFFLINE';

  const clock = now.toLocaleTimeString('en-GB', { hour12: false });
  const date = now
    .toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    .toUpperCase();

  const nav = (
    <ul className="py-2">
      {NAV.map((item) => {
        const active = tab === item.id;
        return (
          <li key={item.id}>
            <button
              type="button"
              disabled={!item.enabled}
              aria-current={active ? 'page' : undefined}
              onClick={() => {
                setView(item.id);
                setNavOpen(false);
              }}
              className={`group relative flex w-full items-center gap-3 px-4 py-3 text-left transition-colors disabled:cursor-not-allowed ${
                active ? 'bg-neon/10' : 'hover:bg-white/[0.03]'
              }`}
            >
              <span
                aria-hidden="true"
                className={`absolute left-0 top-0 h-full w-[3px] transition-colors ${
                  active ? 'bg-crim shadow-[0_0_10px_#FF003C]' : 'bg-transparent group-hover:bg-zinc-700'
                }`}
              />
              <item.icon size={15} style={{ color: active ? '#FCE205' : '#71717a' }} aria-hidden="true" />
              <span
                className={`font-display text-[13px] font-bold uppercase tracking-[0.15em] ${
                  active ? 'text-neon glow-neon' : item.enabled ? 'text-zinc-300' : 'text-zinc-600'
                }`}
              >
                {item.label}
              </span>
              <span className="ml-auto font-mono text-[10px] text-zinc-500">
                {item.enabled ? item.code : 'SOON'}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="relative min-h-screen bg-void">
      <div aria-hidden="true" className="hud-grid pointer-events-none fixed inset-0 opacity-80" />
      <div aria-hidden="true" className="scanlines pointer-events-none fixed inset-0 z-40 opacity-15" />
      <div aria-hidden="true" className="vignette pointer-events-none fixed inset-0 z-40" />

      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:bg-neon focus:px-3 focus:py-2 focus:font-mono focus:text-[11px] focus:text-void"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-zinc-800 bg-char/95 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2">
          <div className="flex items-center gap-2.5">
            <div className="chamfer-sm flex h-9 w-9 items-center justify-center bg-cy">
              <ShieldCheck size={17} className="text-void" aria-hidden="true" />
            </div>
            <div className="leading-none">
              <div className="font-display text-[19px] font-bold tracking-[0.22em] text-white">
                SENTINEL<span className="text-cy glow-cy">//</span>CORE
              </div>
              <div className="mt-0.5 font-mono text-[9px] tracking-[0.2em] text-zinc-400">
                CAPABILITY &amp; SECURITY TERMINAL
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 border-l border-zinc-800 pl-4">
            <Activity
              size={14}
              className={apiState === 'REACHABLE' ? 'text-cy' : apiState === 'OFFLINE' ? 'text-crim' : 'text-zinc-500'}
              aria-hidden="true"
            />
            <span className="font-mono text-[11px] tracking-[0.14em] text-zinc-400">
              API:{' '}
              <span className={apiState === 'REACHABLE' ? 'text-cy' : apiState === 'OFFLINE' ? 'text-crim' : 'text-zinc-400'}>
                {apiState}
              </span>
            </span>
          </div>

          <div className="hidden items-center gap-2 md:flex">
            <span className="font-mono text-[13px] tracking-[0.1em] text-cy glow-cy">
              <span className="sr-only">Time </span>
              {clock}
            </span>
            <span className="font-mono text-[10px] text-zinc-500">/ {date}</span>
          </div>

          <button
            type="button"
            onClick={() => setNavOpen((open) => !open)}
            aria-expanded={navOpen}
            aria-controls="section-nav"
            className="ml-auto flex items-center gap-2 chamfer-xs border border-zinc-700 px-3 py-1.5 font-mono text-[10px] tracking-[0.16em] text-zinc-300 md:hidden"
          >
            {navOpen ? <X size={13} aria-hidden="true" /> : <MenuIcon size={13} aria-hidden="true" />}
            SECTIONS
          </button>
        </div>
      </header>

      <div className="md:grid md:grid-cols-[196px_1fr]">
        <nav
          id="section-nav"
          aria-label="Sections"
          className={`${navOpen ? 'block' : 'hidden'} border-b border-zinc-800 bg-char/70 md:sticky md:top-[57px] md:block md:h-[calc(100vh-57px)] md:overflow-y-auto md:border-b-0 md:border-r`}
        >
          <div className="px-4 pt-3 font-mono text-[9px] tracking-[0.24em] text-zinc-500">SUBSYSTEMS</div>
          {nav}
        </nav>

        <main id="main" className="min-w-0 p-4">
          <h1 className="sr-only">Sentinel capability and security terminal</h1>
          {tab === 'overview' && <Overview live={live} />}
          {tab === 'repository' && <Repository events={live.events} />}
        </main>
      </div>
    </div>
  );
}
