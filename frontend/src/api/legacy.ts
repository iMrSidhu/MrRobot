import {
  SEVERITIES,
  type Dossier,
  type Finding,
  type Mapped,
  type RepoDetailResponse,
  type Section,
  type SecurityValue,
  type Severity,
  type SynthesisValue,
} from './types';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

/** `dropped` counts entries that were not strings — counted, never invented. */
function asStringList(value: unknown): { list: string[]; dropped: number } {
  if (value === undefined || value === null) return { list: [], dropped: 0 };
  if (!Array.isArray(value)) return { list: [], dropped: 0 };
  const list = value.filter((item): item is string => typeof item === 'string' && item.trim() !== '');
  return { list, dropped: value.length - list.length };
}

export function toSeverity(raw: string): Severity | 'UNKNOWN' {
  const upper = raw.trim().toUpperCase();
  return (SEVERITIES as readonly string[]).includes(upper) ? (upper as Severity) : 'UNKNOWN';
}

function mapFinding(value: unknown): Finding | null {
  if (!isRecord(value)) return null;
  const description = asString(value.description);
  if (!description) return null; // a row with no description is unusable, not an empty finding
  const severityRaw = typeof value.severity === 'string' ? value.severity : '';
  return {
    severity: toSeverity(severityRaw),
    severityRaw: severityRaw || 'UNKNOWN',
    file: asString(value.file),
    line: typeof value.line === 'number' && Number.isInteger(value.line) ? value.line : null,
    description,
    mitigation: asString(value.mitigation),
  };
}

function mapSynthesis(raw: unknown): Section<SynthesisValue> {
  if (raw === null || raw === undefined) {
    return { state: 'unavailable', reason: 'No synthesis artifact for this repository.' };
  }
  if (!isRecord(raw)) {
    return { state: 'invalid', reason: 'Synthesis artifact is not a JSON object.' };
  }
  const claims = asStringList(raw.marketing_claims);
  const reality = asStringList(raw.verified_reality);
  const gaps = asStringList(raw.gaps);
  const tags = asStringList(raw.capability_tags);

  return {
    state: 'available',
    dropped: claims.dropped + reality.dropped + gaps.dropped + tags.dropped,
    value: {
      architecture: asString(raw.architecture),
      claims: claims.list,
      reality: reality.list,
      gaps: gaps.list,
      tags: tags.list,
    },
  };
}

function mapSecurity(raw: unknown): Section<SecurityValue> {
  if (raw === null || raw === undefined) {
    return {
      state: 'unavailable',
      // The distinction that matters most: missing is not clean.
      reason: 'No security artifact. This is missing data, not a clean scan.',
    };
  }
  if (!isRecord(raw)) {
    return { state: 'invalid', reason: 'Security artifact is not a JSON object.' };
  }
  if (!Array.isArray(raw.findings)) {
    return { state: 'invalid', reason: 'Security artifact has no findings array.' };
  }
  const findings = raw.findings
    .map(mapFinding)
    .filter((finding): finding is Finding => finding !== null);

  return {
    state: 'available',
    dropped: raw.findings.length - findings.length,
    value: { findings },
  };
}

/**
 * The single place v1 shapes become display data (integration design §6). Anything
 * unparseable surfaces as an explicit invalid/unavailable section — never as a
 * zero, an empty list or a guessed pairing.
 */
export function mapRepoDetail(raw: unknown): Mapped<Dossier> {
  if (!isRecord(raw)) return { ok: false, error: 'Repository response is not an object.' };
  if (!isRecord(raw.repo)) return { ok: false, error: 'Repository response has no repo object.' };

  const repo = raw.repo;
  const id = typeof repo.id === 'number' ? repo.id : null;
  const name = asString(repo.name);
  if (id === null || name === null) {
    return { ok: false, error: 'Repository is missing its id or name.' };
  }

  const detail = raw as unknown as RepoDetailResponse;

  return {
    ok: true,
    value: {
      repo: {
        id,
        name,
        url: asString(repo.url) ?? '',
        stars: typeof repo.stars === 'number' ? repo.stars : 0,
        status: asString(repo.status) ?? 'UNKNOWN',
        updatedAt: asString(repo.timestamp) ?? '',
        error: asString(repo.error),
      },
      provenance: 'legacy_unverified',
      synthesis: mapSynthesis(detail.synthesis),
      security: mapSecurity(detail.security),
      markdownReport: asString(repo.security_report_path) ? 'available' : 'unavailable',
    },
  };
}
