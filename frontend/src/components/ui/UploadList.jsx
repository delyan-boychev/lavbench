import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RotateCcw, X } from 'lucide-react';
import Badge from './Badge';
import Button from './Button';
import { useApiErrorText } from '../../hooks/useApiError';
import { formatBytes, formatDuration } from '../../utils/formatUnits';

// A rate is meaningless in the first moments of an upload
const MIN_ELAPSED_MS = 1000;

/** Seconds left at the average rate so far, or null while it cannot be told. */
function secondsLeft(item, now) {
  const elapsed = now - item.startedAt;
  if (item.status !== 'uploading' || item.loaded <= 0 || elapsed < MIN_ELAPSED_MS) return null;
  return ((item.size - item.loaded) / item.loaded) * (elapsed / 1000);
}

/**
 * The rows of an upload queue (see hooks/useUploadQueue): state, progress, time left,
 * the reason of a failure, and Cancel or Retry per row, under one overall line. A removal row
 * reads "Remove <name>" and has no size or progress.
 *
 * @param {{
 *   items: import('../../hooks/useUploadQueue').UploadItem[],
 *   onCancel: (id: number) => void,
 *   onRetry: (id: number) => void,
 *   title?: React.ReactNode,
 * }} props
 */
export default function UploadList({ items, onCancel, onRetry, title = null }) {
  const { t, i18n } = useTranslation();
  const formatApiError = useApiErrorText();
  const locale = i18n.language || 'en';
  const [now, setNow] = useState(() => Date.now());
  const ticking = items.some((it) => it.status === 'uploading' || (it.retryAt && it.retryAt > now));
  const listRef = useRef(null);
  const count = items.length;
  const failed = items
    .filter((it) => it.status === 'failed')
    .map((it) => it.id)
    .join(',');

  // After Save, and when a row fails, bring it into view above the sticky form footer
  useEffect(() => {
    if (count === 0) return;
    const target = failed ? listRef.current?.querySelector('[data-failed]') : listRef.current;
    target?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [count, failed]);

  // Tick once a second for the time left and a Retry-After countdown, only while one runs
  useEffect(() => {
    if (!ticking) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);

  if (items.length === 0) return null;

  const done = items.filter((it) => it.status === 'done').length;
  const totalBytes = items.reduce((sum, it) => sum + it.size, 0);
  const loadedBytes = items.reduce((sum, it) => sum + it.loaded, 0);

  return (
    <section
      ref={listRef}
      className="flex flex-col gap-3 bg-slate-900/40 p-4 rounded-xl border border-white/5 scroll-mb-28"
      aria-label={t('upload_list.title')}
      data-testid="upload-list"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider">
          {title || t('upload_list.title')}
        </h3>
        <p className="text-xs text-slate-400" role="status" data-testid="upload-overall">
          {t('upload_list.overall', {
            count: items.length,
            done,
            loaded: formatBytes(loadedBytes, locale),
            total: formatBytes(totalBytes, locale),
          })}
        </p>
      </div>
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const percent = item.size > 0 ? Math.round((item.loaded / item.size) * 100) : 0;
          const left = secondsLeft(item, now);
          const showBar = item.status === 'uploading' || item.status === 'checking';
          const waitS = item.retryAt > now ? Math.ceil((item.retryAt - now) / 1000) : 0;
          return (
            <li
              key={item.id}
              className="flex flex-col gap-2 p-3 bg-slate-950 border border-white/5 rounded-lg text-xs scroll-mb-28"
              data-testid={`${item.remove ? 'remove' : 'upload'}-row-${item.name}`}
              data-failed={item.status === 'failed' || undefined}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-slate-200 truncate min-w-0 flex-1">
                  {item.remove ? t('upload_list.remove_name', { name: item.name }) : item.name}
                </span>
                {!item.remove && (
                  <span className="text-slate-500 text-[10px] shrink-0">
                    {formatBytes(item.size, locale)}
                  </span>
                )}
                <span className="shrink-0">
                  <Badge status={`upload_${item.status}`} />
                </span>
                {(item.status === 'waiting' || item.status === 'uploading') && (
                  <Button
                    variant="secondary"
                    className="shrink-0 whitespace-nowrap"
                    onClick={() => onCancel(item.id)}
                    aria-label={t(
                      item.remove ? 'upload_list.cancel_remove' : 'upload_list.cancel_file',
                      { name: item.name },
                    )}
                  >
                    <X size={14} aria-hidden="true" />
                    {t('common.cancel')}
                  </Button>
                )}
                {(item.status === 'failed' || item.status === 'cancelled') && (
                  <Button
                    variant="secondary"
                    className="shrink-0 whitespace-nowrap"
                    onClick={() => onRetry(item.id)}
                    disabled={waitS > 0}
                    aria-label={t(
                      item.remove ? 'upload_list.retry_remove' : 'upload_list.retry_file',
                      { name: item.name },
                    )}
                  >
                    <RotateCcw size={14} aria-hidden="true" />
                    {t('upload_list.retry')}
                  </Button>
                )}
              </div>
              {showBar && (
                <div className="flex items-center gap-3">
                  <div
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={percent}
                    aria-label={item.name}
                    className="h-2 flex-1 rounded-full bg-slate-800 overflow-hidden"
                  >
                    <div
                      className="h-full bg-indigo-500 transition-[width] duration-200"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                  <span className="text-slate-300 shrink-0">{percent}%</span>
                  {left !== null && (
                    <span className="text-slate-500 shrink-0">
                      {t('upload_list.time_left', {
                        time: formatDuration(Math.max(1, left), locale),
                      })}
                    </span>
                  )}
                </div>
              )}
              {item.status === 'failed' && (
                <p className="text-rose-400" role="alert">
                  {formatApiError(
                    item.error?.code ? item.error : null,
                    item.remove ? 'upload_list.remove_failed' : 'upload_list.failed',
                  )}
                </p>
              )}
              {waitS > 0 && (
                <p className="text-amber-300" role="status">
                  {t('upload_list.retry_in', { count: waitS })}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
