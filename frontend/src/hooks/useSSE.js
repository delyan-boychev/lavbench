import { useState, useEffect, useRef, useCallback } from 'react';

export default function useSSE(url, opts = {}) {
  const {
    reconnect = true,
    reconnectDelay = 1000,
    maxReconnectDelay = 15000,
    maxReconnects = 5,
    onMessage,
    onError,
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
      setRetrying(false);
      setError(null);
    };

    es.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const parsed = JSON.parse(event.data);
        if (onMessageRef.current) {
          onMessageRef.current(parsed);
        }
        if (storeData) {
          setData(parsed);
        }
      } catch (err) {
        console.warn('Failed to parse SSE JSON payload:', err, event.data);
      }
    };

    es.onerror = () => {
      if (!mountedRef.current) return;
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
