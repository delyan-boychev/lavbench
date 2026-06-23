import React, { useState, useRef, useEffect } from 'react';
import Badge from '../ui/Badge';
import CodePreview from '../ui/CodePreview';
import EmptyState from '../ui/EmptyState';
import { Star } from 'lucide-react';
import ToggleField from '../ui/ToggleField';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';

export default function SubmissionViewer({
  submission,
  currentUser,
  onSelectFinal,
  selectingFinal = false,
  isSelectionDisabled = false,
  isSubmissionAfterDeadline = false,
}) {
  const { t } = useTranslation();
  const [liveLogs, setLiveLogs] = useState('');
  const [currentId, setCurrentId] = useState(null);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTo({
        top: logRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [liveLogs, submission?.logs]);

  useEffect(() => {
    if (submission && submission.id !== currentId) {
      setCurrentId(submission.id);
      setLiveLogs('');
    }
  }, [submission?.id]);

  useEffect(() => {
    if (!submission) {
      return;
    }

    setLiveLogs('');

    const sseUrl = `/api/submissions/${submission.id}/logs/live`;

    const eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.log) {
          setLiveLogs((prev) => prev + data.log + '\n');
        } else if (data.status) {
          eventSource.close();
        }
      } catch (err) {
        console.error('Failed to parse live log line:', err);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [submission?.id, submission?.status]);

  if (!submission) {
    return (
      <EmptyState
        minHeight={300}
        message={t('submissions.select_to_view')}
        icon={<FileText size={32} className="text-slate-500" />}
      />
    );
  }

  let cells;
  try {
    cells =
      typeof submission.code_cells === 'string'
        ? JSON.parse(submission.code_cells)
        : submission.code_cells || [];
  } catch {
    cells = [];
  }
  // Normalize string cells to objects with source property
  cells = (cells || []).map((cell) =>
    typeof cell === 'string' ? { type: 'code', source: cell } : cell,
  );

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = currentUser?.role === 'admin' || currentUser?.role === 'jury';
  const showUserDemographics =
    isAdminOrJury && submission.user && (submission.user.name || submission.user.username);

  return (
    <div className="flex flex-col gap-4">
      {/* Main Details Card */}
      <div className="surface p-5">
        <div className="flex flex-wrap justify-between gap-3 mb-3.5">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <span className="font-mono text-xs text-slate-500">
                {t('submissions.submission_id', { id: submission.id })}
              </span>
              <Badge status={submission.status} />
              {submission.detailed_status && submission.detailed_status !== submission.status && (
                <Badge status={submission.detailed_status} />
              )}
              {submission.is_final_selection && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400 inline-flex items-center gap-1">
                  <Star className="w-3 h-3" />
                  {t('submissions.final_selection_star')}
                </span>
              )}
            </div>

            {submission.user?.alias_id && (
              <span className="text-[11px] text-slate-400 font-mono">
                {t('submissions.alias', { alias: submission.user?.alias_id })}
              </span>
            )}
          </div>
          <div className="flex gap-4 items-start">
            {submission.public_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                  {t('submissions.public_score')}
                </div>
                <div className="font-mono text-base font-bold text-indigo-400">
                  {Number(submission.public_score).toFixed(4)}
                </div>
              </div>
            )}
            {submission.private_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                  {t('submissions.private_score')}
                </div>
                <div className="font-mono text-base font-bold text-emerald-400">
                  {Number(submission.private_score).toFixed(4)}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Final Selection Selector for Competitor */}
        {isCompetitor && submission.status === 'completed' && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <ToggleField
              id={`final-check-${submission.id}`}
              checked={submission.is_final_selection}
              disabled={selectingFinal || submission.is_final_selection || isSelectionDisabled}
              onChange={() => onSelectFinal && onSelectFinal(submission.id)}
              label={
                submission.is_final_selection
                  ? t('submissions.selected_final_help')
                  : t('submissions.select_final_label')
              }
            />
            {isSelectionDisabled && !submission.is_final_selection && (
              <p className="text-[10px] text-rose-400 mt-1.5 font-semibold">
                {isSubmissionAfterDeadline
                  ? t('submissions.cannot_select_late')
                  : t('submissions.cannot_select_closed')}
              </p>
            )}
          </div>
        )}

        {/* Demographics View for Jury/Admin */}
        {showUserDemographics && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.demographics_title')}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div>
                <strong>{t('submissions.name')}</strong> {submission.user.name}{' '}
                {submission.user.surname}
              </div>
              <div>
                <strong>{t('submissions.username')}</strong> {submission.user.username}
              </div>
              {submission.user.grade && (
                <div>
                  <strong>{t('submissions.grade')}</strong> {submission.user.grade}
                </div>
              )}
              {submission.user.school && (
                <div>
                  <strong>{t('submissions.school')}</strong> {submission.user.school}
                </div>
              )}
              {submission.user.city && (
                <div>
                  <strong>{t('submissions.city')}</strong> {submission.user.city}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Integrity View for Jury/Admin */}
        {isAdminOrJury && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.integrity_title')}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div>
                <strong>{t('submissions.celery_task_id')}</strong>{' '}
                <span className="font-mono text-[11px] text-slate-400">
                  {submission.celery_task_id || t('common.none')}
                </span>
              </div>
              <div>
                <strong>{t('submissions.execution_time')}</strong>{' '}
                {submission.execution_time_ms ? `${submission.execution_time_ms} ms` : '—'}
              </div>
            </div>
          </div>
        )}

        {/* Execution Log */}
        {submission.logs || liveLogs ? (
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {submission.status === 'completed' || submission.status === 'failed'
                ? t('submissions.execution_log', 'Execution Log')
                : t('submissions.execution_log_live', 'Execution Log (Live)')}
            </div>
            <pre
              ref={logRef}
              className={`code-panel text-xs font-mono ${
                submission.status === 'completed'
                  ? 'text-slate-200'
                  : submission.status === 'failed'
                    ? 'text-rose-400'
                    : 'text-indigo-300'
              }`}
              style={{
                maxHeight: '400px',
                overflowY: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {submission.logs || liveLogs}
            </pre>
          </div>
        ) : null}
      </div>

      {/* Submitted Code Cells */}
      {cells.length > 0 && (
        <div className="surface p-5">
          <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-3">
            {t('submissions.submitted_code', { count: cells.length })}
          </div>
          <CodePreview cells={cells} defaultCollapsed={true} maxHeight="200px" />
        </div>
      )}
    </div>
  );
}
