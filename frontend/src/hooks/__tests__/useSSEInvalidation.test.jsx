import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import useSSEInvalidation, {
  LIVE_FALLBACK_POLL_MS,
  LIVE_INVALIDATE_WAIT_MS,
  LIVE_STREAM_RETRY_MS,
} from '../useSSEInvalidation';

let instances = [];

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.closed = false;
    instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(data) {
    this.onmessage?.({ data: JSON.stringify(data), lastEventId: '' });
  }
  drop() {
    this.readyState = 0;
    this.onerror?.();
  }
  fail() {
    this.readyState = 2;
    this.onerror?.();
  }
}

const latest = () => instances[instances.length - 1];

function setup(url = '/api/live', queryKey = ['things']) {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined);
  const wrapper = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(({ u }) => useSSEInvalidation(u, queryKey), {
    wrapper,
    initialProps: { u: url },
  });
  return { ...hook, invalidate };
}

describe('useSSEInvalidation', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    instances = [];
    global.EventSource = MockEventSource;
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    global.EventSource = undefined;
  });

  it('collapses a burst of update signals into one jittered invalidation', () => {
    const { invalidate } = setup();
    act(() => {
      latest().open();
      latest().message({ event: 'update' });
      latest().message({ event: 'update' });
      latest().message({ event: 'update' });
    });
    expect(invalidate).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(LIVE_INVALIDATE_WAIT_MS));
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['things'] });

    act(() => latest().message({ event: 'update' }));
    act(() => vi.advanceTimersByTime(LIVE_INVALIDATE_WAIT_MS));
    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it('ignores lifecycle messages and payload fields other than the update signal', () => {
    const { invalidate } = setup();
    act(() => {
      latest().open();
      latest().message({ info: 'connected' });
      latest().message({ event: 'timeout' });
      latest().message({ leaderboard: [] });
    });
    act(() => vi.advanceTimersByTime(10_000));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('polls only while the stream is not connected', () => {
    const { result } = setup();
    expect(result.current.refetchInterval).toBe(LIVE_FALLBACK_POLL_MS);
    act(() => latest().open());
    expect(result.current.connected).toBe(true);
    expect(result.current.refetchInterval).toBe(false);
    act(() => latest().drop());
    expect(result.current.refetchInterval).toBe(LIVE_FALLBACK_POLL_MS);
  });

  it('resyncs once after a reconnect but not on the first open', () => {
    const { invalidate } = setup();
    act(() => latest().open());
    act(() => vi.advanceTimersByTime(10_000));
    expect(invalidate).not.toHaveBeenCalled();

    act(() => latest().drop());
    act(() => latest().open());
    act(() => vi.advanceTimersByTime(LIVE_INVALIDATE_WAIT_MS));
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('retries the stream later after it gives up', () => {
    setup();
    // Eight fatal closes in a row exhaust the default budget
    for (let i = 0; i <= 8; i += 1) {
      act(() => latest().fail());
      act(() => vi.advanceTimersByTime(30_000));
    }
    const count = instances.length;
    act(() => vi.advanceTimersByTime(LIVE_STREAM_RETRY_MS - 30_000 - 1));
    expect(instances).toHaveLength(count);
    act(() => vi.advanceTimersByTime(1));
    expect(instances).toHaveLength(count + 1);
  });

  it('cancels a pending invalidation on unmount', () => {
    const { invalidate, unmount } = setup();
    act(() => {
      latest().open();
      latest().message({ event: 'update' });
    });
    unmount();
    act(() => vi.advanceTimersByTime(10_000));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('opens no stream for an empty url and keeps polling', () => {
    const { result } = setup('');
    expect(instances).toHaveLength(0);
    expect(result.current.refetchInterval).toBe(LIVE_FALLBACK_POLL_MS);
  });

  it('falls back to polling when EventSource is unavailable', () => {
    global.EventSource = undefined;
    const { result } = setup();
    expect(instances).toHaveLength(0);
    expect(result.current.refetchInterval).toBe(LIVE_FALLBACK_POLL_MS);
  });
});
