import { useCallback, useEffect, useRef, useState } from 'react';
import { uploadWithProgress } from '../services/upload';
import { ApiRequestError, requireOk } from '../services/apiResult';
import { useUnsavedChanges } from './useUnsavedChanges';

/**
 * @typedef {'waiting' | 'uploading' | 'checking' | 'done' | 'failed' | 'cancelled'} UploadStatus
 * @typedef {{
 *   id: number,
 *   name: string,
 *   size: number,
 *   file: Blob,
 *   path: string,
 *   contentType?: string,
 *   status: UploadStatus,
 *   loaded: number,
 *   startedAt: number,
 *   error: ApiRequestError | null,
 *   retryAt: number,
 * }} UploadItem
 * @typedef {{ file: Blob & { name?: string }, path: string, contentType?: string, name?: string }} UploadEntry
 */

const TERMINAL = new Set(['done', 'failed', 'cancelled']);
// A long Retry-After still lets the queue move on after a minute, as useRetryAfter does
const MAX_PAUSE_S = 60;

/** Whether an upload is still to finish. */
export const isActive = (/** @type {UploadItem} */ item) => !TERMINAL.has(item.status);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * A sequential upload queue on the XHR helper: one file at a time, a failure moves on to the
 * next file, and every row can be cancelled or retried. While anything runs, leaving the page
 * asks first.
 * @param {{ onItemDone?: (data: any, item: UploadItem) => void }} [options]
 */
export function useUploadQueue(options = {}) {
  const [items, setItems] = useState(/** @type {UploadItem[]} */ ([]));
  const itemsRef = useRef(/** @type {UploadItem[]} */ ([]));
  const controllers = useRef(new Map());
  const pumping = useRef(false);
  const nextId = useRef(1);
  /** @type {React.MutableRefObject<{ ids: Set<number>, resolve: (ok: boolean) => void }[]>} */
  const batches = useRef([]);
  const onItemDone = useRef(options.onItemDone);
  const mounted = useRef(true);

  useEffect(() => {
    onItemDone.current = options.onItemDone;
  });

  const publish = (next) => {
    itemsRef.current = next;
    if (mounted.current) setItems(next);
  };
  const update = (id, patch) =>
    publish(itemsRef.current.map((it) => (it.id === id ? { ...it, ...patch } : it)));

  // A batch resolves once each of its rows has finished, true when all of them are done
  const settleBatches = () => {
    batches.current = batches.current.filter((batch) => {
      const mine = itemsRef.current.filter((it) => batch.ids.has(it.id));
      if (mine.some(isActive)) return true;
      batch.resolve(mine.every((it) => it.status === 'done'));
      return false;
    });
  };

  /** Send one row; resolves with the seconds to pause before the next one. */
  const run = async (/** @type {UploadItem} */ item) => {
    const controller = new AbortController();
    controllers.current.set(item.id, controller);
    update(item.id, { status: 'uploading', loaded: 0, startedAt: Date.now(), error: null });
    try {
      const result = await uploadWithProgress(item.path, item.file, {
        contentType: item.contentType,
        signal: controller.signal,
        // Every byte sent: the server is now checking the file
        onProgress: (fraction) =>
          update(
            item.id,
            fraction >= 1
              ? { loaded: item.size, status: 'checking' }
              : { loaded: fraction * item.size },
          ),
      });
      requireOk(result);
      update(item.id, { status: 'done', loaded: item.size });
      onItemDone.current?.(result.data, item);
      return 0;
    } catch (error) {
      if (error?.name === 'AbortError') {
        update(item.id, { status: 'cancelled' });
        return 0;
      }
      const refusal = error instanceof ApiRequestError ? error : null;
      // A rate limit or a busy checker says when to come back; the queue waits that long
      const pause = Math.min(refusal?.retryAfter || 0, MAX_PAUSE_S);
      update(item.id, {
        status: 'failed',
        error: refusal,
        retryAt: pause > 0 ? Date.now() + pause * 1000 : 0,
      });
      return pause;
    } finally {
      controllers.current.delete(item.id);
    }
  };

  const pump = async () => {
    if (pumping.current) return;
    pumping.current = true;
    try {
      for (;;) {
        const next = itemsRef.current.find((it) => it.status === 'waiting');
        if (!next || !mounted.current) break;
        const pause = await run(next);
        settleBatches();
        if (pause > 0) await sleep(pause * 1000);
      }
    } finally {
      pumping.current = false;
      settleBatches();
    }
  };

  /**
   * Queue files behind the ones already waiting; resolves true when every one of them is done.
   * @param {UploadEntry[]} entries
   * @returns {Promise<boolean>}
   */
  const enqueue = (entries) => {
    if (entries.length === 0) return Promise.resolve(true);
    const added = entries.map((entry) => ({
      id: nextId.current++,
      name: entry.name || entry.file.name || '',
      size: entry.file.size,
      file: entry.file,
      path: entry.path,
      contentType: entry.contentType,
      status: /** @type {UploadStatus} */ ('waiting'),
      loaded: 0,
      startedAt: 0,
      error: null,
      retryAt: 0,
    }));
    // Finished rows of an earlier save make way; failed and cancelled ones keep their Retry
    publish([...itemsRef.current.filter((it) => it.status !== 'done'), ...added]);
    const done = new Promise((resolve) => {
      batches.current.push({ ids: new Set(added.map((it) => it.id)), resolve });
    });
    pump();
    return /** @type {Promise<boolean>} */ (done);
  };

  const cancel = useCallback((id) => {
    const item = itemsRef.current.find((it) => it.id === id);
    if (!item) return;
    if (item.status === 'waiting') {
      update(id, { status: 'cancelled' });
      settleBatches();
    } else if (item.status === 'uploading') {
      controllers.current.get(id)?.abort();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback((id) => {
    const item = itemsRef.current.find((it) => it.id === id);
    if (!item || isActive(item) || item.retryAt > Date.now()) return;
    update(id, { status: 'waiting', loaded: 0, error: null, retryAt: 0 });
    pump();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const cancelAll = useCallback(() => {
    itemsRef.current.filter(isActive).forEach((it) => cancel(it.id));
  }, [cancel]);

  // Closing the form stops what is still running
  useEffect(() => {
    mounted.current = true;
    const running = controllers.current;
    return () => {
      mounted.current = false;
      running.forEach((controller) => controller.abort());
    };
  }, []);

  const running = items.some(isActive);
  useUnsavedChanges(running);

  return { items, running, enqueue, cancel, retry, cancelAll };
}
