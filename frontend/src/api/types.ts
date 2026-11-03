/**
 * Contracts for the existing SQLite-backed Sentinel API (v1).
 *
 * Raw shapes mirror `dashboard/api.py` + `shared/models.py` exactly. Display shapes
 * (`Dossier`, `Section`) are what pages render; the translation lives in `legacy.ts`
 * so no page has to know about v1 quirks.
 */

export const REPO_STATUSES = [
  'QUEUED',
  'CLONING',
  'PROCESSED',
  'ANALYZING',
  'ANALYZED',
  'DONE',
  'FAILED_AUDIT',
] as const;

export type RepoStatus = (typeof REPO_STATUSES)[number];

/* ---------------------------------------------------------------- raw (v1) */

export type RepoRow = {
  id: number;
  name: string;
  url: string;
  stars: number;
  /** Widened on purpose: rows written by older/newer workers may hold other values. */
  status: string;
  synthesis_path: string | null;
  security_report_path: string | null;
  security_json_path: string | null;
  error: string | null;
  timestamp: string;
};

export type RepoDetailResponse = {
  repo: RepoRow;
  synthesis: unknown | null;
  security: unknown | null;
};

export type HealthResponse = { status: string; db: string };

export type ReportResponse = { path: string; markdown: string };

/* ------------------------------------------------------------ display (v1) */

export const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;

export type Severity = (typeof SEVERITIES)[number];

export type Finding = {
  severity: Severity | 'UNKNOWN';
  /** Exactly what the artifact said, so an unrecognised value is still visible. */
  severityRaw: string;
  file: string | null;
  line: number | null;
  description: string;
  mitigation: string | null;
};

/**
 * A section is never silently empty: "unavailable" means the artifact is missing,
 * "invalid" means it was present but unreadable. Neither is ever shown as a clean result.
 */
export type Section<T> =
  | { state: 'available'; value: T; dropped: number }
  | { state: 'unavailable'; reason: string }
  | { state: 'invalid'; reason: string };

export type SynthesisValue = {
  architecture: string | null;
  claims: string[];
  /** Kept separate from `claims`: v1 gives no guaranteed pairing. */
  reality: string[];
  gaps: string[];
  tags: string[];
};

export type SecurityValue = { findings: Finding[] };

export type Dossier = {
  repo: {
    id: number;
    name: string;
    url: string;
    stars: number;
    status: string;
    updatedAt: string;
    error: string | null;
  };
  /** v1 artifacts predate SHA/evidence pairing, so this is always unverified. */
  provenance: 'legacy_unverified';
  synthesis: Section<SynthesisValue>;
  security: Section<SecurityValue>;
  markdownReport: 'available' | 'unavailable';
};

export type Mapped<T> = { ok: true; value: T } | { ok: false; error: string };
