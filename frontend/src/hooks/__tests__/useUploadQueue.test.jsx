import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { uploadWithProgress } from '../../services/upload';
import { useUploadQueue } from '../useUploadQueue';

vi.mock('../../services/upload', () => ({ uploadWithProgress: vi.fn() }));

/** @type {{ path: string, options: any, resolve: (v: any) => void, reject: (e: any) => void }[]} */
let calls = [];

const file = (name, size = 100) => new File(['x'.repeat(size)], name);
const entry = (name, size) => ({ file: file(name, size), path: `/tasks/t1/files/${name}` });
const ok = (data = { id: 't1' }) => ({
  ok: true,
  status: 200,
  data,
  res: { headers: { get: () => null } },
});
const refused = (status, data, retryAfter = null) => ({
  ok: false,
  status,
  data,
  res: { headers: { get: (name) => (name === 'Retry-After' ? retryAfter : null) } },
});
const statuses = (result) => result.current.items.map((it) => `${it.name}:${it.status}`);

describe('useUploadQueue', () => {
  beforeEach(() => {
    calls = [];
    uploadWithProgress.mockReset();
    uploadWithProgress.mockImplementation(
      (path, _body, options) =>
        new Promise((resolve, reject) => {
          calls.push({ path, options, resolve, reject });
          options.signal?.addEventListener('abort', () =>
            reject(new DOMException('cancelled', 'AbortError')),
          );
        }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('uploads one file at a time, in order, and reports each finished one', async () => {
    const onItemDone = vi.fn();
    const { result } = renderHook(() => useUploadQueue({ onItemDone }));
    let batch;
    act(() => {
      batch = result.current.enqueue([entry('a.csv'), entry('b.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].path).toBe('/tasks/t1/files/a.csv');
    expect(statuses(result)).toEqual(['a.csv:uploading', 'b.csv:waiting']);
    expect(result.current.running).toBe(true);

    await act(async () => calls[0].resolve(ok({ id: 't1', files: ['a.csv'] })));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(onItemDone).toHaveBeenCalledWith(
      { id: 't1', files: ['a.csv'] },
      expect.objectContaining({ name: 'a.csv' }),
    );
    expect(calls[1].path).toBe('/tasks/t1/files/b.csv');

    await act(async () => calls[1].resolve(ok()));
    await expect(batch).resolves.toBe(true);
    expect(statuses(result)).toEqual(['a.csv:done', 'b.csv:done']);
    expect(result.current.running).toBe(false);
  });

  it('turns to Checking once every byte is sent', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([{ ...entry('big.zip', 200), contentType: 'application/zip' }]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].options.contentType).toBe('application/zip');
    act(() => calls[0].options.onProgress(0.5));
    expect(result.current.items[0]).toMatchObject({ status: 'uploading', loaded: 100 });
    act(() => calls[0].options.onProgress(1));
    expect(result.current.items[0]).toMatchObject({ status: 'checking', loaded: 200 });
  });

  it('keeps going with the next file after a refusal and keeps the reason', async () => {
    const { result } = renderHook(() => useUploadQueue());
    let batch;
    act(() => {
      batch = result.current.enqueue([entry('labels.parquet'), entry('train.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () =>
      calls[0].resolve(refused(422, { code: 'ERR_INVALID_LABELS_SCHEMA', error: 'bad' })),
    );
    await waitFor(() => expect(calls).toHaveLength(2));
    await act(async () => calls[1].resolve(ok()));
    await expect(batch).resolves.toBe(false);
    expect(statuses(result)).toEqual(['labels.parquet:failed', 'train.csv:done']);
    expect(result.current.items[0].error).toMatchObject({ code: 'ERR_INVALID_LABELS_SCHEMA' });
  });

  it('marks a network failure as failed with no reason of its own', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => calls[0].reject(new TypeError('network')));
    expect(result.current.items[0]).toMatchObject({ status: 'failed', error: null });
  });

  it('cancels the running file and moves on, and cancels a waiting one before it starts', async () => {
    const { result } = renderHook(() => useUploadQueue());
    let batch;
    act(() => {
      batch = result.current.enqueue([entry('a.csv'), entry('b.csv'), entry('c.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const [, b, c] = result.current.items;
    act(() => result.current.cancel(b.id));
    expect(statuses(result)[1]).toBe('b.csv:cancelled');

    await act(async () => result.current.cancel(result.current.items[0].id));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].path).toBe('/tasks/t1/files/c.csv');
    await act(async () => calls[1].resolve(ok()));
    await expect(batch).resolves.toBe(false);
    expect(statuses(result)).toEqual(['a.csv:cancelled', 'b.csv:cancelled', 'c.csv:done']);
    expect(c.status).toBe('waiting');
  });

  it('retries a failed file', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => calls[0].reject(new TypeError('network')));
    act(() => result.current.retry(result.current.items[0].id));
    await waitFor(() => expect(calls).toHaveLength(2));
    await act(async () => calls[1].resolve(ok()));
    expect(statuses(result)).toEqual(['a.csv:done']);
  });

  it('waits out a rate limit before the next file', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv'), entry('b.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () =>
      calls[0].resolve(refused(429, { code: 'ERR_RATE_LIMITED', error: 'slow down' }, '5')),
    );
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(calls).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    await waitFor(() => expect(calls).toHaveLength(2));
  });

  it('cancels everything still to finish', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv'), entry('b.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => result.current.cancelAll());
    await waitFor(() => expect(result.current.running).toBe(false));
    expect(statuses(result)).toEqual(['a.csv:cancelled', 'b.csv:cancelled']);
    expect(calls).toHaveLength(1);
  });

  it('asks before the page unloads while files upload', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);

    await act(async () => calls[0].resolve(ok()));
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it('stops the running upload when the form closes', async () => {
    const { result, unmount } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    unmount();
    expect(calls[0].options.signal.aborted).toBe(true);
  });

  it('drops the finished rows of an earlier save but keeps failed ones', async () => {
    const { result } = renderHook(() => useUploadQueue());
    act(() => {
      result.current.enqueue([entry('a.csv'), entry('b.csv')]);
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => calls[0].resolve(ok()));
    await waitFor(() => expect(calls).toHaveLength(2));
    await act(async () => calls[1].reject(new TypeError('network')));
    act(() => {
      result.current.enqueue([entry('c.csv')]);
    });
    expect(statuses(result).slice(0, 2)).toEqual(['b.csv:failed', 'c.csv:uploading']);
  });
});
