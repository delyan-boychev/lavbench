import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StrictMode } from 'react';
import { renderHook, act } from '@testing-library/react';
import useSSE from '../useSSE';

const CONNECTING = 0;
const OPEN = 1;
const CLOSED = 2;

/** @type {MockEventSource[]} */
let instances = [];

class MockEventSource {
  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.readyState = CONNECTING;
    this.closed = false;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    instances.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = CLOSED;
  }

  open() {
    this.readyState = OPEN;
    this.onopen?.();
  }

  message(data, lastEventId = '') {
    this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data), lastEventId });
  }

  // The browser keeps the source and reconnects on its own after a dropped connection
  drop() {
    this.readyState = CONNECTING;
    this.onerror?.();
  }

  // HTTP 204, any other non-200 answer, or a wrong Content-Type
  fail() {
    this.readyState = CLOSED;
    this.onerror?.();
  }
}

const latest = () => instances[instances.length - 1];

describe('useSSE', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    instances = [];
    global.EventSource = MockEventSource;
    // Math.random() = 0.5 makes the jitter factor exactly 1
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    global.EventSource = undefined;
  });

  it('connects with credentials when a url is given', () => {
    renderHook(() => useSSE('/api/test'));
    expect(instances).toHaveLength(1);
    expect(latest().url).toBe('/api/test');
    expect(latest().options.withCredentials).toBe(true);
  });

  it('does not connect when the url is empty', () => {
    renderHook(() => useSSE(''));
    expect(instances).toHaveLength(0);
  });

  it('reports connected on open and calls onOpen', () => {
    const onOpen = vi.fn();
    const { result } = renderHook(() => useSSE('/api/test', { onOpen }));
    act(() => latest().open());
    expect(result.current.connected).toBe(true);
    expect(result.current.retrying).toBe(false);
    expect(result.current.error).toBeNull();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('passes parsed JSON payloads to onMessage', () => {
    const onMessage = vi.fn();
    renderHook(() => useSSE('/api/test', { onMessage }));
    act(() => {
      latest().open();
      latest().message({ event: 'update' });
    });
    expect(onMessage).toHaveBeenCalledWith({ event: 'update' });
  });

  it('warns on a non-JSON payload without calling onMessage', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useSSE('/api/test', { onMessage }));
    act(() => latest().message('not-json'));
    expect(warn).toHaveBeenCalled();
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('leaves a dropped connection to the browser instead of recreating the source', () => {
    const onOpen = vi.fn();
    const { result } = renderHook(() => useSSE('/api/test', { onOpen }));
    const source = latest();
    act(() => source.open());
    act(() => source.drop());

    expect(source.closed).toBe(false);
    expect(result.current.connected).toBe(false);
    expect(result.current.retrying).toBe(true);
    act(() => vi.advanceTimersByTime(60_000));
    expect(instances).toHaveLength(1);

    // The native reconnect succeeds on the same source
    act(() => source.open());
    expect(result.current.connected).toBe(true);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it('reconnects manually after a fatal close, with exponential backoff', () => {
    const { result } = renderHook(() =>
      useSSE('/api/test', { reconnectDelay: 1000, maxReconnectDelay: 3000 }),
    );
    const first = latest();
    act(() => first.fail());
    expect(first.closed).toBe(true);
    expect(result.current.retrying).toBe(true);

    act(() => vi.advanceTimersByTime(999));
    expect(instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(instances).toHaveLength(2);

    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(1999));
    expect(instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(instances).toHaveLength(3);

    // Capped at maxReconnectDelay
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(2999));
    expect(instances).toHaveLength(3);
    act(() => vi.advanceTimersByTime(1));
    expect(instances).toHaveLength(4);
  });

  it.each([
    [0, 700],
    [0.999999, 1300],
  ])('jitters the manual reconnect delay by 30%% (random %s)', (random, delay) => {
    Math.random.mockReturnValue(random);
    renderHook(() => useSSE('/api/test', { reconnectDelay: 1000 }));
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(delay - 1));
    expect(instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(instances).toHaveLength(2);
  });

  it('passes the last event id as a query parameter on a manual reconnect', () => {
    const { rerender } = renderHook(({ url }) => useSSE(url, { reconnectDelay: 1000 }), {
      initialProps: { url: '/api/logs?page=1' },
    });
    act(() => {
      latest().open();
      latest().message({ log: 'a' }, 'evt 41');
      latest().message({ log: 'b' }, '');
    });
    act(() => latest().drop());
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(1000));
    expect(latest().url).toBe('/api/logs?page=1&lastEventId=evt%2041');

    // A new stream URL starts without a resume id
    rerender({ url: '/api/other' });
    expect(latest().url).toBe('/api/other');
  });

  it('uses ? for the first query parameter', () => {
    renderHook(() => useSSE('/api/test', { reconnectDelay: 1000 }));
    act(() => latest().message({ log: 'a' }, '7'));
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(1000));
    expect(latest().url).toBe('/api/test?lastEventId=7');
  });

  it('gives up after maxReconnects fatal closes with a translated error', () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useSSE('/api/test', { reconnectDelay: 1000, maxReconnects: 2, onError }),
    );
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(1000));
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(2000));
    expect(instances).toHaveLength(3);
    act(() => latest().fail());

    expect(result.current.error).toBe('Connection lost');
    expect(result.current.retrying).toBe(false);
    expect(onError).toHaveBeenCalledWith('Connection lost');
    act(() => vi.advanceTimersByTime(60_000));
    expect(instances).toHaveLength(3);
  });

  it('does not reconnect after a fatal close when reconnect is false', () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useSSE('/api/test', { reconnect: false, onError }));
    act(() => latest().fail());
    expect(result.current.error).toBe('Connection lost');
    expect(onError).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(60_000));
    expect(instances).toHaveLength(1);
  });

  it('resets the backoff budget after a successful open', () => {
    const { result } = renderHook(() =>
      useSSE('/api/test', { reconnectDelay: 1000, maxReconnects: 1 }),
    );
    act(() => latest().fail());
    act(() => vi.advanceTimersByTime(1000));
    act(() => latest().open());
    act(() => latest().fail());
    expect(result.current.error).toBeNull();
    expect(result.current.retrying).toBe(true);
    act(() => vi.advanceTimersByTime(1000));
    expect(instances).toHaveLength(3);
  });

  it('stops for good on a message accepted by isTerminal', () => {
    const onMessage = vi.fn();
    const { result } = renderHook(() =>
      useSSE('/api/test', { onMessage, isTerminal: (m) => m.status === 'completed' }),
    );
    const source = latest();
    act(() => {
      source.open();
      source.message({ status: 'completed' });
    });
    expect(onMessage).toHaveBeenCalledWith({ status: 'completed' });
    expect(source.closed).toBe(true);
    expect(source.onerror).toBeNull();
    expect(result.current.connected).toBe(false);
    act(() => vi.advanceTimersByTime(60_000));
    expect(instances).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it.each([[{ event: 'evicted' }], [{ code: 'ERR_SSE_SOCKET_LIMIT', error: 'too many' }]])(
    'stops on the server terminal message %j',
    (msg) => {
      renderHook(() => useSSE('/api/test'));
      act(() => {
        latest().open();
        latest().message(msg);
      });
      expect(latest().closed).toBe(true);
      act(() => vi.advanceTimersByTime(60_000));
      expect(instances).toHaveLength(1);
    },
  );

  it('closes the source on unmount and cancels a pending reconnect', () => {
    const { unmount } = renderHook(() => useSSE('/api/test', { reconnectDelay: 1000 }));
    act(() => latest().fail());
    unmount();
    act(() => vi.advanceTimersByTime(60_000));
    expect(instances).toHaveLength(1);

    const second = renderHook(() => useSSE('/api/test'));
    const source = latest();
    second.unmount();
    expect(source.closed).toBe(true);
  });

  it('ignores messages after unmount', () => {
    const onMessage = vi.fn();
    const { unmount } = renderHook(() => useSSE('/api/test', { onMessage }));
    const source = latest();
    unmount();
    source.onmessage?.({ data: '{"event":"update"}', lastEventId: '' });
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('switches streams when the url changes and resets on an empty url', () => {
    const { result, rerender } = renderHook(({ url }) => useSSE(url, { reconnect: false }), {
      initialProps: { url: '/api/first' },
    });
    const first = latest();
    act(() => first.open());
    rerender({ url: '/api/second' });
    expect(first.closed).toBe(true);
    expect(latest().url).toBe('/api/second');
    expect(result.current.connected).toBe(false);

    act(() => latest().fail());
    expect(result.current.error).toBe('Connection lost');
    rerender({ url: '' });
    expect(result.current.error).toBeNull();
    expect(result.current.connected).toBe(false);
    expect(result.current.retrying).toBe(false);
  });

  it('reconnect() starts a fresh session after giving up', () => {
    const { result } = renderHook(() => useSSE('/api/test', { reconnect: false }));
    act(() => latest().fail());
    expect(result.current.error).toBe('Connection lost');

    act(() => result.current.reconnect());
    expect(instances).toHaveLength(2);
    expect(result.current.error).toBeNull();
    act(() => latest().open());
    expect(result.current.connected).toBe(true);
  });

  it('connects under a StrictMode double mount', () => {
    renderHook(() => useSSE('/api/strict'), { wrapper: StrictMode });
    expect(latest().url).toBe('/api/strict');
    expect(latest().closed).toBe(false);
    expect(instances.filter((s) => !s.closed)).toHaveLength(1);
  });
});
