import React from 'react';
import { useTranslation } from 'react-i18next';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import LoadingIndicator from '../ui/LoadingIndicator';
import QueryErrorState from '../ui/QueryErrorState';
import { SYSTEM_STATUS_POLL_MS, useSystemStatusQuery } from '../../hooks/useSystemStatusQuery';
import { formatDateTime, formatUtcTime } from '../../utils/formatDate';
import { formatDuration, formatGigabytes, formatTimeAgo } from '../../utils/formatUnits';
import Notice from '../ui/Notice';

const PANEL = 'bg-[#0d0e18] border border-white/5 p-6 rounded-2xl';
const CAPTION = 'caption-top text-left text-sm font-bold text-white px-1 pb-3';
const NUMERIC = 'text-right tabular-nums';

function StatusItem({ label, hint = '', status }) {
  return (
    <div className="flex flex-col gap-1.5">
      <dt className="text-slate-400 font-bold text-[10px] uppercase tracking-wider">{label}</dt>
      <dd className="flex flex-col gap-1">
        <span>
          <Badge status={status} />
        </span>
        {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
      </dd>
    </div>
  );
}

function CountItem({ label, value }) {
  return (
    <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl">
      <dt className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">{label}</dt>
      <dd className="text-xl font-extrabold text-white mt-1 tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * Seconds between a heartbeat and the moment the server computed the status. Both
 * times come from the server, so the browser clock does not skew the age.
 */
function heartbeatAge(lastSeen, updatedAt) {
  const age = (new Date(updatedAt).getTime() - new Date(lastSeen).getTime()) / 1000;
  return Number.isFinite(age) ? Math.max(0, age) : null;
}

export default function WorkersStats() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language || 'en';
  const { data, error, isLoading, isError, isFetching, refetch } = useSystemStatusQuery();

  const apiError = /** @type {{ code?: string, error?: string } | null} */ (error);
  const errorMessage = apiError?.code ? t(`api.${apiError.code}`, apiError.error) : '';
  const na = t('common.not_available');

  const header = (
    <div className={`${PANEL} flex flex-wrap justify-between items-center gap-4`}>
      <div>
        <h2 className="text-xl font-bold text-white mb-1">{t('admin.workers.title')}</h2>
        <p className="text-slate-400 text-xs">
          {t('admin.workers.description', { seconds: SYSTEM_STATUS_POLL_MS / 1000 })}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {data && (
          <span className="text-xs text-slate-500">
            {t('admin.workers.updated_at', { time: formatUtcTime(data.updated_at) })}
          </span>
        )}
        <Button
          variant="secondary"
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-xs"
        >
          {isFetching ? t('admin.workers.refreshing') : t('admin.workers.refresh_now')}
        </Button>
      </div>
    </div>
  );

  if (isLoading || (isError && !data)) {
    return (
      <div className="flex flex-col gap-6 animate-fadein">
        {header}
        {isLoading ? (
          <LoadingIndicator className="py-12" />
        ) : (
          <QueryErrorState message={errorMessage} onRetry={() => refetch()} />
        )}
      </div>
    );
  }
  if (!data) return null;

  const { submissions, queues, workers } = data;

  return (
    <div className="flex flex-col gap-6 animate-fadein">
      {header}

      {isError && (
        <Notice tone="warning" role="alert">
          {t('admin.workers.refresh_failed', { time: formatUtcTime(data.updated_at) })}
          {errorMessage && ` ${errorMessage}`}
        </Notice>
      )}

      <section className={PANEL} aria-labelledby="system-status-heading">
        <h3 id="system-status-heading" className="text-sm font-bold text-white mb-4">
          {t('admin.workers.status_heading')}
        </h3>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <StatusItem label={t('admin.workers.overall_status')} status={data.status} />
          <StatusItem
            label={t('admin.workers.component_api')}
            hint={t('admin.workers.component_api_hint')}
            status={data.components.api}
          />
          <StatusItem
            label={t('admin.workers.component_scoring')}
            hint={t('admin.workers.component_scoring_hint')}
            status={data.components.scoring}
          />
        </dl>
      </section>

      <section aria-labelledby="submission-counts-heading">
        <h3 id="submission-counts-heading" className="text-sm font-bold text-white mb-3 px-1">
          {t('admin.workers.submissions_heading')}
        </h3>
        <dl className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <CountItem label={t('admin.workers.queued')} value={submissions.queued} />
          <CountItem label={t('admin.workers.running')} value={submissions.running} />
          <CountItem
            label={t('admin.workers.oldest_queued')}
            value={
              submissions.oldest_queued_seconds == null
                ? t('admin.workers.nothing_queued')
                : formatDuration(submissions.oldest_queued_seconds, locale)
            }
          />
          <CountItem
            label={t('admin.workers.completed_last_15m')}
            value={submissions.completed_last_15m}
          />
          <CountItem
            label={t('admin.workers.failed_last_15m')}
            value={submissions.failed_last_15m}
          />
        </dl>
      </section>

      <div className={`${PANEL} overflow-x-auto`}>
        <table className="data-table">
          <caption className={CAPTION}>{t('admin.workers.queues_caption')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('admin.workers.queue_name')}</th>
              <th scope="col" className="text-right">
                {t('admin.workers.consumers')}
              </th>
              <th scope="col" className="text-right">
                {t('admin.workers.queued')}
              </th>
            </tr>
          </thead>
          <tbody>
            {queues.length === 0 ? (
              <tr>
                <td colSpan={3} className="text-center text-slate-500 italic">
                  {t('admin.workers.no_queues')}
                </td>
              </tr>
            ) : (
              queues.map((queue) => (
                <tr key={queue.name}>
                  <td className="font-mono font-semibold">{queue.name}</td>
                  <td className={`${NUMERIC} ${queue.consumers === 0 ? 'text-rose-400' : ''}`}>
                    {queue.consumers}
                  </td>
                  <td className={NUMERIC}>{queue.queued}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className={`${PANEL} overflow-x-auto`}>
        <table className="data-table">
          <caption className={CAPTION}>{t('admin.workers.workers_caption')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('admin.workers.worker_name')}</th>
              <th scope="col">{t('admin.workers.worker_type')}</th>
              <th scope="col">{t('admin.workers.worker_queues')}</th>
              <th scope="col">{t('admin.workers.worker_status')}</th>
              <th scope="col">{t('admin.workers.last_seen')}</th>
              <th scope="col" className="text-right">
                {t('admin.workers.concurrency')}
              </th>
              <th scope="col" className="text-right">
                {t('admin.workers.cpu_cores')}
              </th>
              <th scope="col" className="text-right">
                {t('admin.workers.ram')}
              </th>
              <th scope="col">{t('admin.workers.gpu')}</th>
            </tr>
          </thead>
          <tbody>
            {workers.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center text-slate-500 italic">
                  {t('admin.workers.no_workers')}
                </td>
              </tr>
            ) : (
              workers.map((worker) => {
                const age = worker.last_seen
                  ? heartbeatAge(worker.last_seen, data.updated_at)
                  : null;
                return (
                  <tr key={worker.name}>
                    <td className="font-mono font-semibold break-all">{worker.name}</td>
                    <td className="uppercase">{worker.type}</td>
                    <td className="font-mono">{worker.queues.join(', ') || na}</td>
                    <td>
                      <Badge status={worker.online ? 'online' : 'stale'} />
                    </td>
                    <td className="whitespace-nowrap">
                      {worker.last_seen && age !== null ? (
                        <time
                          dateTime={worker.last_seen}
                          title={formatDateTime(worker.last_seen, 'UTC')}
                        >
                          {formatTimeAgo(age, locale)}
                        </time>
                      ) : (
                        na
                      )}
                    </td>
                    <td className={NUMERIC}>{worker.concurrency ?? na}</td>
                    <td className={NUMERIC}>{worker.cpu_cores ?? na}</td>
                    <td className={`${NUMERIC} whitespace-nowrap`}>
                      {worker.ram_gb != null ? formatGigabytes(worker.ram_gb, locale) : na}
                    </td>
                    <td>
                      {worker.gpu_type
                        ? worker.vram_gb != null
                          ? `${worker.gpu_type} (${formatGigabytes(worker.vram_gb, locale)})`
                          : worker.gpu_type
                        : t('admin.workers.no_gpu')}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
