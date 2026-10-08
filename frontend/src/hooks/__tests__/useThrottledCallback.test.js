import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useThrottledCallback from '../useThrottledCallback';

describe('useThrottledCallback', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('runs the first call immediately and collapses a burst into one trailing call', () => {
    const fn = vi.fn();
    const { result } = renderHook(() => useThrottledCallback(fn, 1000));

    act(() => {
      result.current();
      result.current();
      result.current();
    });
    expect(fn).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(999));
    expect(fn).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(1));
    expect(fn).toHaveBeenCalledTimes(2);

    act(() => vi.advanceTimersByTime(5000));
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('runs immediately again once the cooldown has elapsed', () => {
    const fn = vi.fn();
    const { result } = renderHook(() => useThrottledCallback(fn, 1000));

    act(() => result.current());
    act(() => vi.advanceTimersByTime(1500));
    act(() => result.current());
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('returns a stable function and calls the latest callback', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result, rerender } = renderHook(({ cb }) => useThrottledCallback(cb, 1000), {
      initialProps: { cb: first },
    });
    const throttled = result.current;

    act(() => result.current());
    rerender({ cb: second });
    expect(result.current).toBe(throttled);

    act(() => result.current());
    act(() => vi.advanceTimersByTime(1000));
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('cancels a pending trailing call on unmount', () => {
    const fn = vi.fn();
    const { result, unmount } = renderHook(() => useThrottledCallback(fn, 1000));

    act(() => {
      result.current();
      result.current();
    });
    unmount();
    act(() => vi.advanceTimersByTime(2000));
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
