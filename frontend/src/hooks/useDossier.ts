import { fetchRepoDetail } from '../api/client';
import { mapRepoDetail } from '../api/legacy';
import type { Dossier, Mapped } from '../api/types';
import { useResource } from './useResource';

/** One repository's artifacts, already through the compatibility mapper. Refetches when `revision` changes. */
export function useDossier(repoId: number | null, revision = 0) {
  return useResource<Mapped<Dossier> | null>(
    repoId === null ? 'dossier:none' : `dossier:${repoId}:${revision}`,
    async (signal) => {
      if (repoId === null) return null;
      return mapRepoDetail(await fetchRepoDetail(repoId, signal));
    },
  );
}
