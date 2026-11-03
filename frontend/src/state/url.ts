import { useCallback, useEffect, useState } from 'react';

export function readParam(key: string): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

export function writeParam(key: string, value: string | null): void {
  const params = new URLSearchParams(window.location.search);
  if (value === null || value === '') params.delete(key);
  else params.set(key, value);
  const search = params.toString();
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`,
  );
}

/**
 * URL query as React state: selection survives reload, is shareable, and a
 * pasted link opens the same view (integration design §7).
 */
export function useParam(key: string): [string | null, (value: string | null) => void] {
  const [value, setValue] = useState(() => readParam(key));

  useEffect(() => {
    const onPop = () => setValue(readParam(key));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [key]);

  const update = useCallback(
    (next: string | null) => {
      writeParam(key, next);
      setValue(next);
    },
    [key],
  );

  return [value, update];
}
