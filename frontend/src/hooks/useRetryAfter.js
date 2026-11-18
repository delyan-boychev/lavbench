import { useEffect, useState } from 'react';

// A long Retry-After still leaves the button usable after a minute
const MAX_WAIT_S = 60;

/**
 * Honour an error's Retry-After: `wait(error)` starts a countdown, and `secondsLeft` is 0
 * once the button may be pressed again. Nothing is retried automatically.
 */
export function useRetryAfter() {
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  // One timer ends the wait on time; a second ticks the countdown once a second
  useEffect(() => {
    if (!until) return undefined;
    const end = setTimeout(() => setUntil(0), Math.max(0, until - Date.now()));
    return () => clearTimeout(end);
  }, [until]);

  useEffect(() => {
    if (!until) return undefined;
    const tick = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(tick);
  }, [until, now]);

  /** @param {{ retryAfter?: number | null } | null | undefined} error */
  const wait = (error) => {
    const seconds = Number(error?.retryAfter);
    if (!(seconds > 0)) return;
    const current = Date.now();
    setNow(current);
    setUntil(current + Math.min(seconds, MAX_WAIT_S) * 1000);
  };

  const secondsLeft = until ? Math.max(1, Math.ceil((until - now) / 1000)) : 0;
  return { secondsLeft, waiting: secondsLeft > 0, wait };
}
