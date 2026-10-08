import { useCallback, useEffect, useRef } from 'react';

/**
 * Return a stable function that calls `callback` at most once per `wait` ms.
 * The first call runs immediately; calls during the cooldown collapse into one trailing run.
 * @param {() => void} callback
 * @param {number} [wait]
 * @returns {() => void}
 */
export default function useThrottledCallback(callback, wait = 1500) {
  const callbackRef = useRef(callback);
  const lastRunRef = useRef(0);
  const timerRef = useRef(/** @type {ReturnType<typeof setTimeout> | null} */ (null));

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    },
    [],
  );

  return useCallback(() => {
    if (timerRef.current !== null) return;
    const elapsed = Date.now() - lastRunRef.current;
    if (elapsed >= wait) {
      lastRunRef.current = Date.now();
      callbackRef.current();
      return;
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      lastRunRef.current = Date.now();
      callbackRef.current();
    }, wait - elapsed);
  }, [wait]);
}
