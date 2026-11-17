import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import EmptyState from '../ui/EmptyState';
import LoadingIndicator from '../ui/LoadingIndicator';
import QueryErrorState from '../ui/QueryErrorState';
import { useWorkspacesQuery } from '../../hooks/useEnvironmentQuery';
import { formatLocalizedDate } from '../../utils/formatDate';

/**
 * Read-only list of every registered student with their workspace and latest submission.
 * @param {{ challengeId: string, environmentId: string, timezone: string, refetchInterval?: number | false }} props
 */
export default function WorkspaceList({ challengeId, environmentId, timezone, refetchInterval }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { data, isPending, isError, refetch } = useWorkspacesQuery(challengeId, environmentId, {
    enabled: open,
    refetchInterval,
  });
  const rows = data || [];
  const opened = rows.filter((row) => row.opened).length;
  const formatTime = (iso) =>
    iso ? formatLocalizedDate(iso, { timeZone: timezone, year: undefined }) : '—';
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="flex flex-col gap-3" data-testid="workspace-list">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => setOpen(!open)}>
          <Chevron size={14} aria-hidden="true" />
          {open ? t('environment.workspaces.hide') : t('environment.workspaces.show')}
        </Button>
        {open && data && (
          <span className="text-xs text-slate-400">
            {t('environment.workspaces.summary', { opened, total: rows.length })}
          </span>
        )}
      </div>
      {open &&
        (isPending ? (
          <LoadingIndicator className="py-6" />
        ) : isError && !data ? (
          <QueryErrorState onRetry={refetch} minHeight={120} />
        ) : rows.length === 0 ? (
          <EmptyState message={t('environment.workspaces.empty')} minHeight={80} surface={false} />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="overflow-x-auto max-h-96 overflow-y-auto border border-white/5 rounded-xl">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">{t('environment.workspaces.student')}</th>
                    <th scope="col">{t('environment.workspaces.first_open')}</th>
                    <th scope="col">{t('environment.workspaces.last_open')}</th>
                    <th scope="col">{t('environment.workspaces.latest_submission')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.user_id}>
                      <td>
                        <span className="font-semibold">{row.alias}</span>
                        {row.username && (
                          <span className="block text-[10px] text-slate-500">{row.username}</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap text-slate-400">
                        {row.opened
                          ? formatTime(row.created_at)
                          : t('environment.workspaces.not_opened')}
                      </td>
                      <td className="whitespace-nowrap text-slate-400">
                        {formatTime(row.last_launched_at)}
                      </td>
                      <td className="whitespace-nowrap">
                        {row.last_submission_status ? (
                          <span className="inline-flex items-center gap-2">
                            <Badge status={row.last_submission_status} />
                            <span className="text-slate-400">
                              {formatTime(row.last_submission_at)}
                            </span>
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[10px] text-slate-500">
              {t('environment.workspaces.times_in', { timezone })}
            </p>
          </div>
        ))}
    </div>
  );
}
