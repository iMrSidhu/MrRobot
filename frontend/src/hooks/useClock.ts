import { useEffect, useState } from 'react';

/**
 * Wall clock, isolated from data fetching on purpose: a one-second tick must not
 * re-render repository/report views (integration design §7).
 */
export function useClock(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return now;
}
