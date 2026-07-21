import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import Pagination from '../ui/Pagination';
import EmptyState from '../ui/EmptyState';
import { FileText } from 'lucide-react';
import useSSE from '../../hooks/useSSE';
import { useQueueQuery } from '../../hooks/useQueueQuery';
import { useClearQueue } from '../../hooks/useSubmissionMutations';
import TaskService from '../../services/TaskService';

export default function SubmissionQueue() {
  const { t } = useTranslation();
  const { currentUser } = useAuth();
  const { showToast, confirm } = useApp();

  const [page, setPage] = useState(1);
  const [killing, setKilling] = useState(null);

  const perPage = 20;

  const { data, refetch } = useQueueQuery(page, perPage);

  const clearQueueMutation = useClearQueue();

  useSSE('/api/admin/submissions/queue/live', {
    onMessage: () => {
      refetch();
    },
  });

  const items = data?.items || [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 1;

  const handleKill = async (submissionId) => {
    const confirmed = await confirm(
      t('admin.submission_queue.kill_confirm'),
      t('admin.submission_queue.kill'),
    );
    if (!confirmed) return;

    setKilling(submissionId);
    try {
      const res = await TaskService.killSubmission(submissionId);
      if (res.ok) {
        showToast(t('submissions.kill_success'), 'emerald');
        refetch();
      } else {
        const err = /** @type {{ code?: string, error?: string }} */ (res.data);
        const errMsg = err.code ? t(`api.${err.code}`, err.error) : t('submissions.kill_failed');
        showToast(errMsg, 'rose');
      }
    } catch {
      showToast(t('submissions.kill_failed'), 'rose');
    } finally {
      setKilling(null);
    }
  };

  const handleClearQueue = async () => {
    const confirmed = await confirm(
      t('admin.submission_queue.clear_queue_confirm'),
      t('admin.submission_queue.clear_queue'),
    );
    if (!confirmed) return;

    try {
      const res = await clearQueueMutation.mutateAsync();
      if (res.ok) {
        showToast(res.data?.message || 'Queue cleared.', 'emerald');
        refetch();
      } else {
        const err = /** @type {{ code?: string, error?: string }} */ (res.data);
        const errMsg = err.code ? t(`api.${err.code}`, err.error) : 'Failed to clear queue';
        showToast(errMsg, 'rose');
      }
    } catch {
      showToast('Network error clearing queue.', 'rose');
    }
  };

  if (total === 0) {
    return (
      <div className="flex flex-col gap-6 animate-fadein">
        <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-wrap justify-between items-center gap-4">
          <div>
            <h2 className="text-xl font-bold text-white mb-1">
              {t('admin.submission_queue.title')}
            </h2>
          </div>
        </div>
        <EmptyState
          minHeight={200}
          message={t('admin.submission_queue.queue_empty')}
          icon={<FileText size={28} className="text-slate-500" />}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 animate-fadein">
      <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white mb-1">{t('admin.submission_queue.title')}</h2>
          <p className="text-slate-400 text-xs">
            {t('admin.submission_queue.queue_description', { count: total })}
          </p>
        </div>
        {currentUser?.role === 'admin' && (
          <Button
            variant="danger"
            onClick={handleClearQueue}
            className="text-xs"
            disabled={clearQueueMutation.isPending}
            isLoading={clearQueueMutation.isPending}
          >
            {t('admin.submission_queue.clear_queue')}
          </Button>
        )}
      </div>

      <div className="bg-[#0d0e18] border border-white/5 rounded-2xl overflow-hidden">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-slate-900/50 text-slate-400 font-bold uppercase border-b border-white/5">
              <th className="p-3">{t('admin.submission_queue.task_header')}</th>
              <th className="p-3">{t('admin.submission_queue.user_header')}</th>
              <th className="p-3">{t('admin.submission_queue.status_header')}</th>
              <th className="p-3">{t('admin.submission_queue.created_header')}</th>
              <th className="p-3">{t('admin.submission_queue.actions_header')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                <td className="p-3 font-mono text-slate-300 font-semibold">
                  {item.task_title || '—'}
                </td>
                <td className="p-3 font-mono text-slate-400">{item.user_alias || '—'}</td>
                <td className="p-3">
                  <Badge status={item.status} />
                </td>
                <td className="p-3 text-slate-400 text-[10px]">
                  {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
                </td>
                <td className="p-3">
                  <Button
                    variant="danger"
                    size="xs"
                    onClick={() => handleKill(item.id)}
                    disabled={killing === item.id}
                  >
                    {killing === item.id ? '...' : t('admin.submission_queue.kill')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex justify-center">
          <Pagination
            page={page}
            pages={pages}
            total={total}
            perPage={perPage}
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  );
}
