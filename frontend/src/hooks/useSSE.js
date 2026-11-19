import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { withJitter } from '../utils/jitter';

// EventSource.CLOSED: the browser gave up on the stream (HTTP 204, any other non-200
// answer, or a wrong Content-Type) and will not reconnect on its own. Test doubles do
// not always define the static, so the value is spelled out
const CLOSED = 2;

// Server control message that ends a stream for good: reconnecting after an
// eviction only evicts another of the user's streams
function isServerTerminal(msg) {
  return msg?.event === 'evicted';
}

// A new EventSource starts with an empty last event id, so a manual reconnect
// carries it in the query string instead of the Last-Event-ID header
function withLastEventId(url, id) {
  return `${url}${url.includes('?') ? '&' : '?'}lastEventId=${encodeURIComponent(id)}`;
}

const IDLE = { key: '', connected: false, retrying: false, failed: false };

/**
 * @typedef {object} SSEOptions
 * @property {boolean} [reconnect] Reconnect manually after a fatal close (default true)
 * @property {number} [reconnectDelay] Base delay of the manual backoff in ms
 * @property {number} [maxReconnectDelay] Upper bound of the manual backoff in ms
 * @property {number} [maxReconnects] Fatal closes in a row before giving up
 * @property {() => void} [onOpen] Called on every successful (re)connect
 * @property {(msg: any) => void} [onMessage] Called with each parsed JSON payload
 * @property {(message: string) => void} [onError] Called once the hook gives up
 * @property {(msg: any) => boolean} [isTerminal] Return true to end the stream for good
 */

/**
 * Subscribe to a Server-Sent Events stream.
 *
 * Dropped connections are left to the browser's own reconnect, which honours the
 * server's `retry:` field. Only a fatal close falls back to a manual reconnect with
 * exponential backoff and plus or minus 30% jitter.
 *
 * @param {string} url Stream URL; an empty string disconnects
 * @param {SSEOptions} [opts]
 * @returns {{ connected: boolean, retrying: boolean, error: string | null, reconnect: () => void }}
 */
export default function useSSE(url, opts = {}) {
  const { t } = useTranslation();
  const [session, setSession] = useState(0);
  const [state, setState] = useState(IDLE);
  const optsRef = useRef(opts);
  const tRef = useRef(t);

  useEffect(() => {
    optsRef.current = opts;
    tRef.current = t;
  });

  useEffect(() => {
    if (!url) return undefined;
    // State left over from another URL or an earlier session is ignored at render
    const key = `${session}|${url}`;
    const update = (patch) =>
      setState((prev) => ({ ...(prev.key === key ? prev : IDLE), ...patch, key }));

    /** @type {EventSource | null} */
    let source = null;
    /** @type {ReturnType<typeof setTimeout> | null} */
    let timer = null;
    let attempts = 0;
    let lastEventId = '';

    const teardown = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (source) {
        source.onopen = null;
        source.onmessage = null;
        source.onerror = null;
        source.close();
        source = null;
      }
    };

    const connect = () => {
      const es = new EventSource(lastEventId ? withLastEventId(url, lastEventId) : url, {
        withCredentials: true,
      });
      source = es;

      es.onopen = () => {
        attempts = 0;
        update({ connected: true, retrying: false, failed: false });
        optsRef.current.onOpen?.();
      };

      es.onmessage = (event) => {
        if (event.lastEventId) lastEventId = event.lastEventId;
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch (err) {
          console.warn('Failed to parse SSE JSON payload:', err, event.data);
          return;
        }
        optsRef.current.onMessage?.(msg);
        if (source !== es) return;
        if (isServerTerminal(msg) || optsRef.current.isTerminal?.(msg)) {
          teardown();
          update({ connected: false, retrying: false });
        }
      };

      es.onerror = () => {
        if (source !== es) return;
        if (es.readyState !== CLOSED) {
          // The browser is already reconnecting on its own schedule
          update({ connected: false, retrying: true });
          return;
        }
        teardown();
        const {
          reconnect = true,
          reconnectDelay = 1000,
          maxReconnectDelay = 30_000,
          maxReconnects = 8,
        } = optsRef.current;
        if (reconnect && attempts < maxReconnects) {
          const delay = withJitter(Math.min(reconnectDelay * 2 ** attempts, maxReconnectDelay));
          attempts += 1;
          update({ connected: false, retrying: true });
          timer = setTimeout(() => {
            timer = null;
            connect();
          }, delay);
        } else {
          update({ connected: false, retrying: false, failed: true });
          optsRef.current.onError?.(tRef.current('common.connection_lost'));
        }
      };
    };

    connect();
    return teardown;
  }, [url, session]);

  const reconnect = useCallback(() => setSession((s) => s + 1), []);

  const current = url && state.key === `${session}|${url}` ? state : IDLE;
  return {
    connected: current.connected,
    retrying: current.retrying,
    error: current.failed ? t('common.connection_lost') : null,
    reconnect,
  };
}
