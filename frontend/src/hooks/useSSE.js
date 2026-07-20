import { useState, useEffect, useRef, useCallback } from 'react';

export default function useSSE(url, opts = {}) {
  const { reconnect = false, reconnectDelay = 5000, maxReconnects = 0, onMessage, onError } = opts;

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);

  const retryCountRef = useRef(0);
  const esRef = useRef(null);
  const mountedRef = useRef(true);
  const urlRef = useRef(url);
  const timeoutRef = useRef(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
  }, [onMessage, onError]);

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
    setError(null);

    const es = new EventSource(urlRef.current, { withCredentials: true });
    esRef.current = es;

    es.onopen = () => {
      if (!mountedRef.current) {
        es.close();
        return;
      }
      retryCountRef.current = 0;
      setConnected(true);
      setError(null);
    };

    es.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const parsed = JSON.parse(event.data);
        if (onMessageRef.current) {
          onMessageRef.current(parsed);
        }
        setData(parsed);
      } catch {
        // Non-JSON data — just ignore
      }
    };

    es.onerror = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      es.close();
      if (reconnect && retryCountRef.current < maxReconnects) {
        retryCountRef.current += 1;
        timeoutRef.current = setTimeout(() => {
          if (mountedRef.current && connectRef.current) connectRef.current();
        }, reconnectDelay);
      } else {
        const msg = 'Connection lost';
        setError(msg);
        if (onErrorRef.current) {
          onErrorRef.current(msg);
        }
      }
    };
  }, [clearConnection, reconnect, reconnectDelay, maxReconnects]);

  useEffect(() => {
    connectRef.current = connect;
  });

  const reconnectFn = useCallback(() => {
    retryCountRef.current = 0;
    connect();
  }, [connect]);

  useEffect(() => {
    urlRef.current = url;
    if (url) {
      connect();
    } else {
      clearConnection();
      setConnected(false);
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

  return { data, error, connected, reconnect: reconnectFn };
}
