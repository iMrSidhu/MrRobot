import { useState } from 'react';
import { AlertTriangle, BookOpen, Download, FolderGit2, ScrollText, ShieldAlert, Tags } from 'lucide-react';
import { fetchRepos, fetchReport } from '../api/client';
import { REFRESH_EVENT_TYPES } from '../api/events';
import type { SentinelEvent } from '../api/events';
import type { Dossier, Finding, Section } from '../api/types';
import Panel from '../components/Panel';
import { useDossier } from '../hooks/useDossier';
import { useResource } from '../hooks/useResource';
import { useParam } from '../state/url';

const PAGE_SIZE = 10;
const FILTERS = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'] as const;
type Filter = (typeof FILTERS)[number];

const SEVERITY_STYLES: Record<string, string> = {
  CRITICAL: 'border-crim/70 text-crim',
  HIGH: 'border-orange-500/70 text-orange-400',
  MEDIUM: 'border-neon/70 text-neon',
  LOW: 'border-zinc-500 text-zinc-300',
  UNKNOWN: 'border-zinc-700 text-zinc-400',
};

function SeverityChip({ severity }: { severity: string }) {
  return (
    <span
      className={`chamfer-xs inline-block border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.14em] ${
        SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.UNKNOWN
      }`}
    >
      {severity}
    </span>
  );
}

/** Missing or unreadable artifacts say so; they never render as an empty success. */
function SectionNotice({ section }: { section: Extract<Section<unknown>, { state: 'unavailable' | 'invalid' }> }) {
  return (
    <div className="flex items-start gap-2 border border-zinc-800 bg-black/30 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-zinc-400">
      <AlertTriangle size={12} className={section.state === 'invalid' ? 'mt-0.5 shrink-0 text-crim' : 'mt-0.5 shrink-0 text-zinc-500'} aria-hidden="true" />
      <span>
        <span className="uppercase tracking-[0.14em] text-zinc-300">{section.state}</span> — {section.reason}
      </span>
    </div>
  );
}

function StringList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="font-mono text-[10px] text-zinc-500">{empty}</p>;
  return (
    <ol className="space-y-1.5">
      {items.map((item, index) => (
        <li key={`${index}-${item.slice(0, 24)}`} className="flex gap-2 font-mono text-[11px] leading-relaxed text-zinc-300">
          <span className="w-6 shrink-0 text-right text-zinc-600">{String(index + 1).padStart(2, '0')}</span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Repository({ events }: { events: SentinelEvent[] }) {
  const [repoParam, setRepoParam] = useParam('repo');
  const repoId = repoParam !== null && /^\d+$/.test(repoParam) ? Number(repoParam) : null;

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<Filter>('ALL');
  const [page, setPage] = useState(1);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const repos = useResource('repos', fetchRepos);
  /** Refetch only when an event actually changes this repository's results. */
  const revision = events.reduce(
    (latest, event) => (event.repoId === repoId && REFRESH_EVENT_TYPES.has(event.type) ? event.id : latest),
    0,
  );
  const dossier = useDossier(repoId, revision);

  const needle = search.trim().toLowerCase();
  const visibleRepos = repos.status === 'ready' ? repos.data.filter((repo) => repo.name.toLowerCase().includes(needle)) : [];

  const mapped = dossier.status === 'ready' && dossier.data?.ok ? dossier.data.value : null;

  async function downloadReport(repo: Dossier['repo']) {
    setReportBusy(true);
    setReportError(null);
    try {
      const markdown = await fetchReport(repo.id);
      const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${repo.name.replace(/[^\w.-]+/g, '-')}-security-report.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setReportError(error instanceof Error ? error.message : String(error));
    } finally {
      setReportBusy(false);
    }
  }

  const findings: Finding[] = mapped?.security.state === 'available' ? mapped.security.value.findings : [];
  const matching = filter === 'ALL' ? findings : findings.filter((finding) => finding.severity === filter);
  const pageCount = Math.max(1, Math.ceil(matching.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageRows = matching.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const severityCount = (severity: string) => findings.filter((finding) => finding.severity === severity).length;

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <aside className="min-w-0">
        <Panel title="Repositories" code={repos.status === 'ready' ? `${repos.data.length}` : '—'} icon={FolderGit2} accent="#00FFFF">
          <label className="mb-2 block">
            <span className="mb-1 block font-mono text-[9px] tracking-[0.2em] text-zinc-500">SEARCH</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="owner/repo"
              className="chamfer-xs w-full border border-zinc-700 bg-black/40 px-2 py-1.5 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-cy focus:outline-none"
            />
          </label>

          {repos.status === 'loading' && <p className="font-mono text-[10px] text-zinc-500">Loading…</p>}
          {repos.status === 'error' && (
            <p role="alert" className="font-mono text-[10px] text-crim">
              {repos.error}
            </p>
          )}
          {repos.status === 'ready' && visibleRepos.length === 0 && (
            <p className="font-mono text-[10px] text-zinc-500">
              {repos.data.length === 0 ? 'No repositories ingested yet.' : 'No match.'}
            </p>
          )}

          <ul className="max-h-[60vh] space-y-0.5 overflow-y-auto">
            {visibleRepos.map((repo) => {
              const active = repo.id === repoId;
              return (
                <li key={repo.id}>
                  <button
                    type="button"
                    aria-current={active ? 'true' : undefined}
                    onClick={() => {
                      setRepoParam(String(repo.id));
                      setFilter('ALL');
                      setPage(1);
                      setReportError(null);
                    }}
                    className={`w-full px-2 py-1.5 text-left transition-colors ${
                      active ? 'bg-neon/10 text-neon' : 'text-zinc-300 hover:bg-white/5'
                    }`}
                  >
                    <span className="block truncate font-mono text-[11px]">{repo.name}</span>
                    <span className="block font-mono text-[9px] tracking-[0.12em] text-zinc-500">
                      {repo.status} · ★{repo.stars.toLocaleString()}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Panel>
      </aside>

      <div className="min-w-0 space-y-4">
        {repoId === null && (
          <Panel title="No Repository Selected" code="REPO-—" icon={FolderGit2} accent="#3f3f46">
            <p className="font-mono text-[11px] text-zinc-400">Select a repository from the list to inspect its artifacts.</p>
          </Panel>
        )}

        {dossier.status === 'loading' && repoId !== null && (
          <p className="font-mono text-[10px] text-zinc-500">Loading repository…</p>
        )}

        {dossier.status === 'error' && (
          <p role="alert" className="border border-crim/50 px-3 py-2 font-mono text-[10px] text-crim">
            {dossier.error}
          </p>
        )}

        {dossier.status === 'ready' && dossier.data && !dossier.data.ok && (
          <div role="alert" className="border border-crim/50 px-3 py-2 font-mono text-[10px] text-crim">
            Compatibility error — {dossier.data.error}
          </div>
        )}

        {mapped && (
          <>
            <Panel
              title={mapped.repo.name || `Repository ${mapped.repo.id}`}
              code={`REPO-${mapped.repo.id}`}
              icon={ShieldAlert}
              accent="#FCE205"
              glow
              action={
                <div className="flex items-center gap-2">
                  {mapped.markdownReport === 'available' && (
                    <button
                      type="button"
                      onClick={() => void downloadReport(mapped.repo)}
                      disabled={reportBusy}
                      className="flex items-center gap-1.5 chamfer-xs border border-zinc-700 px-2 py-1 font-mono text-[10px] tracking-[0.14em] text-zinc-200 hover:border-neon hover:text-neon disabled:opacity-50"
                    >
                      <Download size={11} aria-hidden="true" />
                      {reportBusy ? 'FETCHING…' : 'REPORT.MD'}
                    </button>
                  )}
                  <span className="chamfer-xs border border-cy/60 px-2 py-1 font-mono text-[9px] tracking-[0.14em] text-cy">
                    LEGACY_UNVERIFIED
                  </span>
                </div>
              }
            >
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[11px] sm:grid-cols-4">
                <div>
                  <dt className="text-[9px] tracking-[0.16em] text-zinc-500">STATUS</dt>
                  <dd className="text-zinc-200">{mapped.repo.status}</dd>
                </div>
                <div>
                  <dt className="text-[9px] tracking-[0.16em] text-zinc-500">STARS</dt>
                  <dd className="text-zinc-200">{mapped.repo.stars.toLocaleString()}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-[9px] tracking-[0.16em] text-zinc-500">UPDATED</dt>
                  <dd className="text-zinc-200">{mapped.repo.updatedAt || 'UNKNOWN'}</dd>
                </div>
                <div className="col-span-2 sm:col-span-4">
                  <dt className="text-[9px] tracking-[0.16em] text-zinc-500">SOURCE</dt>
                  <dd className="break-all text-zinc-400">{mapped.repo.url || 'UNKNOWN'}</dd>
                </div>
              </dl>

              {mapped.repo.error && (
                <p className="mt-3 border-t border-crim/40 pt-2 font-mono text-[10px] text-crim">{mapped.repo.error}</p>
              )}
              {reportError && (
                <p role="alert" className="mt-3 border-t border-crim/40 pt-2 font-mono text-[10px] text-crim">
                  Report unavailable — {reportError}
                </p>
              )}
            </Panel>

            <Panel title="Architecture" code="SYNTH-01" icon={BookOpen} accent="#00FFFF">
              {mapped.synthesis.state === 'available' ? (
                mapped.synthesis.value.architecture ? (
                  <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-300">
                    {mapped.synthesis.value.architecture}
                  </p>
                ) : (
                  <p className="font-mono text-[10px] text-zinc-500">No architecture summary recorded.</p>
                )
              ) : (
                <SectionNotice section={mapped.synthesis} />
              )}
            </Panel>

            {mapped.synthesis.state === 'available' && (
              <>
                <Panel
                  title="Marketing Claims"
                  code="SYNTH-02"
                  icon={ScrollText}
                  accent="#FCE205"
                  action={<span className="font-mono text-[9px] tracking-[0.14em] text-zinc-500">UNPAIRED IN V1</span>}
                >
                  <StringList items={mapped.synthesis.value.claims} empty="No claims recorded." />
                  <p className="mt-3 border-t border-zinc-800 pt-2 font-mono text-[9px] leading-relaxed text-zinc-500">
                    v1 does not pair claims with verified evidence, so these are listed as written, not as confirmed statements.
                  </p>
                </Panel>

                <Panel title="Verified Reality" code="SYNTH-03" icon={AlertTriangle} accent="#71717A">
                  <StringList items={mapped.synthesis.value.reality} empty="No verified-reality entries recorded." />
                </Panel>

                <Panel title="Gaps" code="SYNTH-04" icon={AlertTriangle} accent="#FF003C">
                  <StringList items={mapped.synthesis.value.gaps} empty="No gaps recorded." />
                </Panel>

                <Panel title="Capability Tags" code="SYNTH-05" icon={Tags} accent="#00FFFF">
                  {mapped.synthesis.value.tags.length === 0 ? (
                    <p className="font-mono text-[10px] text-zinc-500">No capability tags recorded.</p>
                  ) : (
                    <ul className="flex flex-wrap gap-1.5">
                      {mapped.synthesis.value.tags.map((tag) => (
                        <li key={tag} className="chamfer-xs border border-zinc-700 px-2 py-0.5 font-mono text-[10px] text-zinc-300">
                          {tag}
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </>
            )}

            <Panel
              title="Security Findings"
              code="SEC-AUDIT"
              icon={ShieldAlert}
              accent="#FF003C"
              action={
                mapped.security.state === 'available' ? (
                  <span className="font-mono text-[9px] tracking-[0.14em] text-zinc-400">
                    {findings.length} TOTAL · C{severityCount('CRITICAL')} H{severityCount('HIGH')} M{severityCount('MEDIUM')} L
                    {severityCount('LOW')}
                  </span>
                ) : null
              }
            >
              {mapped.security.state !== 'available' ? (
                <SectionNotice section={mapped.security} />
              ) : (
                <>
                  {mapped.security.dropped > 0 && (
                    <p className="mb-2 border border-neon/40 px-2 py-1 font-mono text-[9px] text-neon">
                      {mapped.security.dropped} malformed finding(s) could not be parsed and are excluded.
                    </p>
                  )}

                  <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Filter findings by severity">
                    {FILTERS.map((value) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={filter === value}
                        onClick={() => {
                          setFilter(value);
                          setPage(1);
                        }}
                        className={`chamfer-xs border px-2 py-0.5 font-mono text-[9px] tracking-[0.12em] ${
                          filter === value ? 'border-cy bg-cy/10 text-cy' : 'border-zinc-700 text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        {value}
                      </button>
                    ))}
                  </div>

                  {matching.length === 0 ? (
                    <p className="font-mono text-[10px] text-zinc-500">No findings match this filter.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse font-mono text-[10px]">
                        <caption className="sr-only">Security findings for {mapped.repo.name}</caption>
                        <thead>
                          <tr className="border-b border-zinc-800 text-left text-[9px] tracking-[0.14em] text-zinc-500">
                            <th scope="col" className="py-1.5 pr-3 font-normal">SEV</th>
                            <th scope="col" className="py-1.5 pr-3 font-normal">LOCATION</th>
                            <th scope="col" className="py-1.5 pr-3 font-normal">FINDING</th>
                            <th scope="col" className="py-1.5 font-normal">MITIGATION</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pageRows.map((finding, index) => (
                            <tr key={`${currentPage}-${index}-${finding.description.slice(0, 20)}`} className="border-b border-zinc-900 align-top">
                              <td className="py-2 pr-3">
                                <SeverityChip severity={finding.severity} />
                              </td>
                              <td className="max-w-[180px] break-all py-2 pr-3 text-zinc-400">
                                {finding.file ?? '—'}
                                {finding.line !== null ? `:${finding.line}` : ''}
                              </td>
                              <td className="py-2 pr-3 leading-relaxed text-zinc-200">{finding.description}</td>
                              <td className="py-2 leading-relaxed text-zinc-400">{finding.mitigation ?? 'Not provided'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {pageCount > 1 && (
                    <div className="mt-2 flex items-center justify-between font-mono text-[9px] tracking-[0.12em] text-zinc-400">
                      <button
                        type="button"
                        onClick={() => setPage(Math.max(1, currentPage - 1))}
                        disabled={currentPage === 1}
                        className="chamfer-xs border border-zinc-700 px-2 py-1 disabled:opacity-40"
                      >
                        PREV
                      </button>
                      <span>
                        PAGE {currentPage}/{pageCount}
                      </span>
                      <button
                        type="button"
                        onClick={() => setPage(Math.min(pageCount, currentPage + 1))}
                        disabled={currentPage === pageCount}
                        className="chamfer-xs border border-zinc-700 px-2 py-1 disabled:opacity-40"
                      >
                        NEXT
                      </button>
                    </div>
                  )}
                </>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
