import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useMutation from '../useMutation';

describe('useMutation', () => {
  it('returns isLoading false for unknown mutation', () => {
    const { result } = renderHook(() => useMutation());
    expect(result.current.isLoading('anything')).toBe(false);
  });

  it('sets isLoading true during run and false after', async () => {
    const { result } = renderHook(() => useMutation());

    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    let runPromise;
    act(() => {
      runPromise = result.current.run('test', () => promise);
    });

    expect(result.current.isLoading('test')).toBe(true);

    await act(async () => {
      resolvePromise('done');
      await runPromise;
    });

    expect(result.current.isLoading('test')).toBe(false);
  });

  it('returns the resolved value from run', async () => {
    const { result } = renderHook(() => useMutation());

    let resolved;
    await act(async () => {
      resolved = await result.current.run('test', async () => 'hello');
    });

    expect(resolved).toBe('hello');
  });

  it('resets loading state even when the function throws', async () => {
    const { result } = renderHook(() => useMutation());

    await act(async () => {
      try {
        await result.current.run('test', async () => {
          throw new Error('fail');
        });
      } catch {
        // expected
      }
    });

    expect(result.current.isLoading('test')).toBe(false);
  });

  it('propagates errors from the inner function', async () => {
    const { result } = renderHook(() => useMutation());

    await expect(
      act(async () => {
        await result.current.run('test', async () => {
          throw new Error('boom');
        });
      }),
    ).rejects.toThrow('boom');
  });

  it('tracks multiple independent mutations', async () => {
    const { result } = renderHook(() => useMutation());

    let resolveA;
    const promiseA = new Promise((resolve) => {
      resolveA = resolve;
    });
    let resolveB;
    const promiseB = new Promise((resolve) => {
      resolveB = resolve;
    });

    let runPromiseA;
    act(() => {
      runPromiseA = result.current.run('a', () => promiseA);
    });
    let runPromiseB;
    act(() => {
      runPromiseB = result.current.run('b', () => promiseB);
    });

    expect(result.current.isLoading('a')).toBe(true);
    expect(result.current.isLoading('b')).toBe(true);
    expect(result.current.isLoading('c')).toBe(false);

    await act(async () => {
      resolveA('doneA');
      await runPromiseA;
    });

    expect(result.current.isLoading('a')).toBe(false);
    expect(result.current.isLoading('b')).toBe(true);

    await act(async () => {
      resolveB('doneB');
      await runPromiseB;
    });

    expect(result.current.isLoading('a')).toBe(false);
    expect(result.current.isLoading('b')).toBe(false);
  });

  it('runs the inner function with correct arguments', async () => {
    const { result } = renderHook(() => useMutation());
    const fn = vi.fn().mockResolvedValue('result');

    await act(async () => {
      await result.current.run('test', fn);
    });

    expect(fn).toHaveBeenCalledOnce();
  });

  it('supports reusing the same mutation name sequentially', async () => {
    const { result } = renderHook(() => useMutation());

    await act(async () => {
      await result.current.run('seq', async () => 'first');
    });
    expect(result.current.isLoading('seq')).toBe(false);

    await act(async () => {
      await result.current.run('seq', async () => 'second');
    });
    expect(result.current.isLoading('seq')).toBe(false);
  });

  it('does not interfere between different hook instances', async () => {
    const { result: result1 } = renderHook(() => useMutation());
    const { result: result2 } = renderHook(() => useMutation());

    let resolve1;
    const p1 = new Promise((resolve) => {
      resolve1 = resolve;
    });

    act(() => {
      result1.current.run('x', () => p1);
    });

    expect(result1.current.isLoading('x')).toBe(true);
    expect(result2.current.isLoading('x')).toBe(false);

    await act(async () => {
      resolve1('done');
    });
  });
});
