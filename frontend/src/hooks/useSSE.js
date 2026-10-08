import { useState, useEffect, useRef, useCallback } from 'react';

// Server control messages that end a stream for good: reconnecting after an
// eviction or a per-user socket limit only evicts another of the user's streams.
function isServerTerminal(msg) {
  return msg?.event === 'evicted' || msg?.code === 'ERR_SSE_SOCKET_LIMIT';
}

// Stream lifecycle notices carry no data; some streams use `event` for real payloads
// (queue snapshots, backup events), so only the known lifecycle values are matched
export function isLifecycleMessage(msg) {
  return (
    msg?.info != null || msg?.code != null || msg?.event === 'timeout' || msg?.event === 'evicted'
  );
}

export default function useSSE(url, opts = {}) {
  const {
    reconnect = true,
    reconnectDelay = 1000,
    maxReconnectDelay = 15000,
    maxReconnects = 5,
    onMessage,
    onError,
    isTerminal,
    storeData = true,
  } = opts;

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const retryCountRef = useRef(0);
  const esRef = useRef(null);
  const mountedRef = useRef(true);
  const urlRef = useRef(url);
  const timeoutRef = useRef(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);
  const isTerminalRef = useRef(isTerminal);
  const stoppedRef = useRef(false);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
    isTerminalRef.current = isTerminal;
  }, [onMessage, onError, isTerminal]);

  const clearConnection = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const connectRef = useRef(null);

  const connect = useCallback(() => {
    if (!urlRef.current || !mountedRef.current) return;

    clearConnection();
    stoppedRef.current = false;
    setError(null);

    const es = new EventSource(urlRef.current, { withCredentials: true });
    esRef.current = es;

    es.onopen = () => {
      if (!mountedRef.current) {
        es.close();
        return;
      }
      setConnected(true);
      setRetrying(false);
      setError(null);
    };

    es.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const parsed = JSON.parse(event.data);
        // Opening alone does not prove the stream is healthy: a server that
        // replays and closes would otherwise reconnect forever at the base delay
        if (!isLifecycleMessage(parsed) || parsed.event === 'timeout') {
          retryCountRef.current = 0;
        }
        if (onMessageRef.current) {
          onMessageRef.current(parsed);
        }
        if (storeData) {
          setData(parsed);
        }
        if (isServerTerminal(parsed) || isTerminalRef.current?.(parsed)) {
          stoppedRef.current = true;
          es.close();
          if (esRef.current === es) esRef.current = null;
          setConnected(false);
          setRetrying(false);
        }
      } catch (err) {
        console.warn('Failed to parse SSE JSON payload:', err, event.data);
      }
    };

    es.onerror = () => {
      if (!mountedRef.current || stoppedRef.current) return;
      setConnected(false);
      es.close();
      if (reconnect && retryCountRef.current < maxReconnects) {
        const retryDelay = Math.min(reconnectDelay * 2 ** retryCountRef.current, maxReconnectDelay);
        retryCountRef.current += 1;
        setRetrying(true);
        timeoutRef.current = setTimeout(() => {
          if (mountedRef.current && connectRef.current) connectRef.current();
        }, retryDelay);
      } else {
        const msg = 'Connection lost';
        setRetrying(false);
        setError(msg);
        if (onErrorRef.current) {
          onErrorRef.current(msg);
        }
      }
    };
  }, [clearConnection, reconnect, reconnectDelay, maxReconnectDelay, maxReconnects, storeData]);

  useEffect(() => {
    connectRef.current = connect;
  });

  const reconnectFn = useCallback(() => {
    retryCountRef.current = 0;
    connect();
  }, [connect]);

  useEffect(() => {
    // StrictMode remounts run this effect before the mount effect below
    mountedRef.current = true;
    urlRef.current = url;
    retryCountRef.current = 0;
    if (url) {
      connect();
    } else {
      clearConnection();
      setConnected(false);
      setRetrying(false);
      setData(null);
      setError(null);
    }
    return clearConnection;
  }, [url, connect, clearConnection]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  return { data, error, connected, retrying, reconnect: reconnectFn };
}
