import { isRecord } from './legacy';
import type { HealthResponse, RepoRow } from './types';

/** Same-origin path. Dev uses the Vite proxy; production serves the frontend beside the API. */
export const API_BASE = '/api';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** The API answered, but not with a shape this build can render. */
export class CompatibilityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CompatibilityError';
  }
}

async function getJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    headers: { accept: 'application/json' },
  });

  if (!response.ok) {
    let detail = '';
    try {
      const body: unknown = await response.json();
      if (isRecord(body) && typeof body.detail === 'string') detail = ` — ${body.detail}`;
    } catch {
      // Error bodies are not guaranteed to be JSON; the status alone is enough.
    }
    throw new ApiError(response.status, `${response.status} ${response.statusText}${detail}`);
  }

  return response.json();
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const body = await getJson('/health', signal);
  if (!isRecord(body) || typeof body.status !== 'string') {
    throw new CompatibilityError('Health response has no status field.');
  }
  // `db` is deliberately not surfaced: internal filesystem paths stay off the HUD
  // (integration design §6).
  return { status: body.status, db: '' };
}

export async function fetchRepos(signal?: AbortSignal): Promise<RepoRow[]> {
  const body = await getJson('/repos', signal);
  if (!Array.isArray(body)) throw new CompatibilityError('Repositories response is not an array.');

  return body.map((row) => {
    if (!isRecord(row) || typeof row.id !== 'number' || typeof row.name !== 'string') {
      throw new CompatibilityError('A repository row is missing its id or name.');
    }
    return row as unknown as RepoRow;
  });
}

/** Raw payload: `mapRepoDetail` turns it into renderable data. */
export function fetchRepoDetail(repoId: number, signal?: AbortSignal): Promise<unknown> {
  return getJson(`/repos/${repoId}`, signal);
}

/** Markdown report for one repository. The API's filesystem `path` is ignored on purpose. */
export async function fetchReport(repoId: number, signal?: AbortSignal): Promise<string> {
  const body = await getJson(`/repos/${repoId}/report`, signal);
  if (!isRecord(body) || typeof body.markdown !== 'string') {
    throw new CompatibilityError('Report response has no markdown field.');
  }
  return body.markdown;
}
