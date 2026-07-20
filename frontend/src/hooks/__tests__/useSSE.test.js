import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useSSE from '../useSSE';

let mockEventSourceInstance;
let onOpenCallback;
let onMessageCallback;
let onErrorCallback;
let closeCount;

class MockEventSource {
  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.readyState = 0;
    mockEventSourceInstance = this;
    onOpenCallback = null;
    onMessageCallback = null;
    onErrorCallback = null;
    Object.defineProperty(this, 'onopen', {
      set(fn) {
        onOpenCallback = fn;
      },
      get() {
        return onOpenCallback;
      },
    });
    Object.defineProperty(this, 'onmessage', {
      set(fn) {
        onMessageCallback = fn;
      },
      get() {
        return onMessageCallback;
      },
    });
    Object.defineProperty(this, 'onerror', {
      set(fn) {
        onErrorCallback = fn;
      },
      get() {
        return onErrorCallback;
      },
    });
  }
  close() {
    closeCount += 1;
    this.readyState = 2;
    mockEventSourceInstance = null;
  }
}

function triggerOpen() {
  if (onOpenCallback) onOpenCallback();
}

function triggerMessage(data) {
  if (onMessageCallback) onMessageCallback({ data: JSON.stringify(data) });
}

function triggerError() {
  if (onErrorCallback) onErrorCallback();
}

describe('useSSE', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    closeCount = 0;
    mockEventSourceInstance = null;
    onOpenCallback = null;
    onMessageCallback = null;
    onErrorCallback = null;
    global.EventSource = MockEventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
    global.EventSource = undefined;
  });

  it('connects when url is provided', () => {
    renderHook(() => useSSE('/api/test'));
    expect(mockEventSourceInstance).not.toBeNull();
    expect(mockEventSourceInstance.url).toBe('/api/test');
    expect(mockEventSourceInstance.options.withCredentials).toBe(true);
  });

  it('does not connect when url is empty', () => {
    renderHook(() => useSSE(''));
    expect(mockEventSourceInstance).toBeNull();
  });

  it('sets connected=true on open', () => {
    const { result } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    expect(result.current.connected).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('sets data from parsed JSON messages', () => {
    const { result } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerMessage({ foo: 'bar' });
    });
    expect(result.current.data).toEqual({ foo: 'bar' });
  });

  it('replaces data on each new message', () => {
    const { result } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerMessage({ step: 1 });
    });
    expect(result.current.data).toEqual({ step: 1 });
    act(() => {
      triggerMessage({ step: 2 });
    });
    expect(result.current.data).toEqual({ step: 2 });
  });

  it('sets connected=false and error on error when reconnect=false', () => {
    const { result } = renderHook(() => useSSE('/api/test', { reconnect: false }));
    act(() => {
      triggerOpen();
    });
    expect(result.current.connected).toBe(true);
    act(() => {
      triggerError();
    });
    expect(result.current.connected).toBe(false);
    expect(result.current.error).toBe('Connection lost');
  });

  it('does not reconnect when reconnect=false', () => {
    renderHook(() => useSSE('/api/test', { reconnect: false }));
    act(() => {
      triggerOpen();
    });
    const initialInstance = mockEventSourceInstance;
    act(() => {
      triggerError();
    });
    expect(mockEventSourceInstance).toBeNull();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(mockEventSourceInstance).toBeNull();
  });

  it('reconnects with fixed delay when reconnect=true', () => {
    renderHook(() =>
      useSSE('/api/test', { reconnect: true, reconnectDelay: 5000, maxReconnects: 3 }),
    );
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerError();
    });

    expect(mockEventSourceInstance).toBeNull();

    act(() => {
      vi.advanceTimersByTime(4999);
    });
    expect(mockEventSourceInstance).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(mockEventSourceInstance).not.toBeNull();
    expect(mockEventSourceInstance.url).toBe('/api/test');
  });

  it('stops reconnecting after maxReconnects consecutive failures', () => {
    const { result } = renderHook(() =>
      useSSE('/api/test', {
        reconnect: true,
        reconnectDelay: 1000,
        maxReconnects: 2,
      }),
    );

    act(() => {
      triggerOpen();
    });

    // 1st error → reconnect
    act(() => {
      triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // 2nd error (without open in between) → last allowed reconnect
    act(() => {
      triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // 3rd error → exhausted, no reconnect
    act(() => {
      triggerError();
    });
    expect(result.current.error).toBe('Connection lost');
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(mockEventSourceInstance).toBeNull();
  });

  it('calls onMessage callback with parsed data', () => {
    const onMessage = vi.fn();
    renderHook(() => useSSE('/api/test', { onMessage }));
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerMessage({ key: 'val' });
    });
    expect(onMessage).toHaveBeenCalledWith({ key: 'val' });
  });

  it('calls onError callback on connection error', () => {
    const onError = vi.fn();
    renderHook(() => useSSE('/api/test', { onError }));
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerError();
    });
    expect(onError).toHaveBeenCalledWith('Connection lost');
  });

  it('closes connection on unmount', () => {
    const { unmount } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    expect(closeCount).toBe(0);
    unmount();
    expect(closeCount).toBe(1);
  });

  it('reconnects when url changes', () => {
    const { rerender } = renderHook(({ url }) => useSSE(url), {
      initialProps: { url: '/api/first' },
    });
    const firstInstance = mockEventSourceInstance;
    expect(firstInstance.url).toBe('/api/first');
    act(() => {
      triggerOpen();
    });

    rerender({ url: '/api/second' });
    // old instance should be closed, new one created
    expect(firstInstance.readyState).toBe(2);
    expect(mockEventSourceInstance.url).toBe('/api/second');
  });

  it('clears state when url changes to empty', () => {
    const { result, rerender } = renderHook(({ url }) => useSSE(url, { onError: () => {} }), {
      initialProps: { url: '/api/test' },
    });
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerMessage({ x: 1 });
    });
    expect(result.current.data).toEqual({ x: 1 });

    rerender({ url: '' });
    expect(result.current.data).toBeNull();
    expect(result.current.connected).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('recovers state from error when reconnecting', () => {
    const { result } = renderHook(() =>
      useSSE('/api/test', {
        reconnect: true,
        reconnectDelay: 1000,
        maxReconnects: 3,
      }),
    );
    act(() => {
      triggerOpen();
    });
    act(() => {
      triggerError();
    });
    expect(result.current.connected).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      triggerOpen();
    });
    expect(result.current.connected).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('reconnect function resets retry count from exhausted state', () => {
    const { result } = renderHook(() =>
      useSSE('/api/test', {
        reconnect: true,
        reconnectDelay: 1000,
        maxReconnects: 2,
      }),
    );
    act(() => {
      triggerOpen();
    });

    // Exhaust retries without any successful open
    act(() => {
      triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      triggerError();
    });
    expect(result.current.error).toBe('Connection lost');

    // Manual reconnect resets retry count
    act(() => {
      result.current.reconnect();
    });
    expect(mockEventSourceInstance).not.toBeNull();
    act(() => {
      triggerOpen();
    });
    expect(result.current.connected).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('ignores non-JSON messages silently', () => {
    const { result } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    act(() => {
      if (onMessageCallback) onMessageCallback({ data: 'not-json' });
    });
    expect(result.current.data).toBeNull();
  });

  it('ignores messages after unmount', () => {
    const { result, unmount } = renderHook(() => useSSE('/api/test'));
    act(() => {
      triggerOpen();
    });
    unmount();
    act(() => {
      triggerMessage({ after: 'unmount' });
    });
    expect(result.current.data).toBeNull();
  });
});
