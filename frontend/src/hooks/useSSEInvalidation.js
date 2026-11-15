import { useCallback, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import useSSE from './useSSE';
import { withJitter } from '../utils/jitter';

// Queries kept fresh by a live stream do not refetch on window focus. They always
// refetch on mount, because no stream listened while they were unmounted
export const LIVE_QUERY_OPTIONS = /** @type {const} */ ({
  staleTime: 5 * 60_000,
  refetchOnMount: 'always',
});

export const LIVE_FALLBACK_POLL_MS = 15_000;
export const LIVE_INVALIDATE_WAIT_MS = 2_000;
export const LIVE_STREAM_RETRY_MS = 60_000;

/**
 * Refetch a query when a signal-only stream sends `{"event": "update"}`.
 *
 * The payload is never read beyond that signal. A burst of events collapses into one
 * invalidation after a jittered delay, a reconnect resyncs once, and the returned
 * `refetchInterval` polls only while the stream is not connected.
 *
 * @param {string} url Stream URL; an empty string disables the stream
 * @param {readonly unknown[]} queryKey Query key (or prefix) to invalidate
 * @param {{ pollMs?: number, waitMs?: number }} [options]
 * @returns {{ connected: boolean, refetchInterval: number | false }}
 */
export default function useSSEInvalidation(url, queryKey, options = {}) {
  const { pollMs = LIVE_FALLBACK_POLL_MS, waitMs = LIVE_INVALIDATE_WAIT_MS } = options;
  const queryClient = useQueryClient();
  const queryKeyRef = useRef(queryKey);
  const timerRef = useRef(/** @type {ReturnType<typeof setTimeout> | null} */ (null));
  const openedUrlRef = useRef('');

  useEffect(() => {
    queryKeyRef.current = queryKey;
  });

  useEffect(
    () => () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    },
    [],
  );

  const scheduleInvalidate = useCallback(() => {
    if (timerRef.current !== null) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      queryClient.invalidateQueries({ queryKey: queryKeyRef.current });
    }, withJitter(waitMs));
  }, [queryClient, waitMs]);

  const streamUrl = typeof EventSource !== 'undefined' ? url : '';
  const { connected, error, reconnect } = useSSE(streamUrl, {
    onOpen: () => {
      // Updates published while the stream was down were missed
      if (openedUrlRef.current === streamUrl) scheduleInvalidate();
      openedUrlRef.current = streamUrl;
    },
    onMessage: (msg) => {
      if (msg?.event === 'update') scheduleInvalidate();
    },
  });

  // Polling covers the gap after the stream gives up; the stream gets another chance later
  useEffect(() => {
    if (!error) return undefined;
    const timer = setTimeout(reconnect, withJitter(LIVE_STREAM_RETRY_MS));
    return () => clearTimeout(timer);
  }, [error, reconnect]);

  return { connected, refetchInterval: connected ? false : pollMs };
}
