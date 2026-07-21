import React, { useState, useRef, useEffect } from 'react';
import Badge from '../ui/Badge';
import CodePreview from '../ui/CodePreview';
import EmptyState from '../ui/EmptyState';
import { Star } from 'lucide-react';
import ToggleField from '../ui/ToggleField';
import useSSE from '../../hooks/useSSE';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import api from '../../services/ApiService';
export default function SubmissionViewer({
  submission,
  currentUser,
  onSelectFinal,
  selectingFinal = false,
  isSelectionDisabled = false,
  isSubmissionAfterDeadline = false,
  onSubmissionUpdate,
  onKill,
  killing = false,
}) {
  const { t } = useTranslation();
  const [liveLogs, setLiveLogs] = useState('');
  const [currentId, setCurrentId] = useState(null);
  const [completedData, setCompletedData] = useState(null);
  const logRef = useRef(null);

  const displaySubmission = completedData ? { ...completedData, ...submission } : submission;
  const isTerminal =
    displaySubmission?.status === 'completed' || displaySubmission?.status === 'failed';
  const displayLogs = isTerminal
    ? displaySubmission?.logs || liveLogs
    : liveLogs || displaySubmission?.logs;

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTo({
        top: logRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [liveLogs, displaySubmission?.logs]);

  useEffect(() => {
    if (submission && submission.id !== currentId) {
      setCurrentId(submission.id);
      setLiveLogs('');
      setCompletedData(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submission?.id]);

  useSSE(submission ? `/api/submissions/${submission.id}/logs/live` : '', {
    onMessage: (data) => {
      if (data.log) {
        setLiveLogs((prev) => prev + data.log + '\n');
      } else if (data.status) {
        if (data.status === 'completed' || data.status === 'failed') {
          api
            .fetch(`/api/submissions/${submission.id}`)
            .then((r) => {
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              return r.json();
            })
            .then((freshData) => {
              setCompletedData(freshData);
              onSubmissionUpdate?.(freshData);
            })
            .catch((err) => {
              console.error('Failed to fetch completed submission:', err);
            });
        }
      }
    },
  });

  if (!displaySubmission) {
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
      typeof displaySubmission.code_cells === 'string'
        ? JSON.parse(displaySubmission.code_cells)
        : displaySubmission.code_cells || [];
  } catch {
    cells = [];
  }
  cells = (cells || []).map((cell) =>
    typeof cell === 'string' ? { type: 'code', source: cell } : cell,
  );

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = currentUser?.role === 'admin' || currentUser?.role === 'jury';
  const showUserDemographics =
    isAdminOrJury &&
    displaySubmission.user &&
    (displaySubmission.user.name || displaySubmission.user.username);

  return (
    <div className="flex flex-col gap-4">
      <div className="surface p-5">
        <div className="flex flex-wrap justify-between gap-3 mb-3.5">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <span className="font-mono text-xs text-slate-500">
                {t('submissions.submission_id', { id: displaySubmission.id })}
              </span>
              <Badge status={displaySubmission.status} />
              {displaySubmission.detailed_status &&
                displaySubmission.detailed_status !== displaySubmission.status && (
                  <Badge status={displaySubmission.detailed_status} />
                )}
              {displaySubmission.is_baseline && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400 inline-flex items-center gap-1">
                  {t('submissions.baseline_label')}
                </span>
              )}
              {displaySubmission.is_final_selection && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400 inline-flex items-center gap-1">
                  <Star className="w-3 h-3" />
                  {t('submissions.final_selection_star')}
                </span>
              )}
              {(displaySubmission.status === 'queued' || displaySubmission.status === 'running') &&
                (currentUser?.role === 'admin' ||
                  currentUser?.role === 'jury' ||
                  (currentUser?.role === 'competitor' &&
                    displaySubmission.user_id === currentUser?.id)) && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onKill && onKill(displaySubmission.id);
                    }}
                    disabled={killing}
                    className="text-xs font-semibold px-3 py-1 rounded-lg border border-rose-600 bg-rose-600/20 text-rose-300 hover:bg-rose-600/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {killing ? '...' : t('submissions.kill')}
                  </button>
                )}
            </div>

            {displaySubmission.user?.alias_id && (
              <span className="text-[11px] text-slate-400 font-mono">
                {t('submissions.alias', { alias: displaySubmission.user?.alias_id })}
              </span>
            )}
          </div>
          <div className="flex gap-4 items-start">
            {displaySubmission.public_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                  {t('submissions.public_score')}
                </div>
                <div className="font-mono text-base font-bold text-indigo-400">
                  {Number(displaySubmission.public_score).toFixed(4)}
                </div>
              </div>
            )}
            {displaySubmission.private_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                  {t('submissions.private_score')}
                </div>
                <div className="font-mono text-base font-bold text-emerald-400">
                  {Number(displaySubmission.private_score).toFixed(4)}
                </div>
              </div>
            )}
          </div>
        </div>

        {isCompetitor && displaySubmission.status === 'completed' && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <ToggleField
              id={`final-check-${displaySubmission.id}`}
              checked={displaySubmission.is_final_selection}
              disabled={
                selectingFinal || displaySubmission.is_final_selection || isSelectionDisabled
              }
              onChange={() => onSelectFinal && onSelectFinal(displaySubmission.id)}
              label={
                displaySubmission.is_final_selection
                  ? t('submissions.selected_final_help')
                  : t('submissions.select_final_label')
              }
            />
            {isSelectionDisabled && !displaySubmission.is_final_selection && (
              <p className="text-[10px] text-rose-400 mt-1.5 font-semibold">
                {isSubmissionAfterDeadline
                  ? t('submissions.cannot_select_late')
                  : t('submissions.cannot_select_closed')}
              </p>
            )}
          </div>
        )}

        {showUserDemographics && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.demographics_title')}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div>
                <strong>{t('submissions.name')}</strong> {displaySubmission.user.name}{' '}
                {displaySubmission.user.surname}
              </div>
              <div>
                <strong>{t('submissions.username')}</strong> {displaySubmission.user.username}
              </div>
              {displaySubmission.user.grade && (
                <div>
                  <strong>{t('submissions.grade')}</strong> {displaySubmission.user.grade}
                </div>
              )}
              {displaySubmission.user.school && (
                <div>
                  <strong>{t('submissions.school')}</strong> {displaySubmission.user.school}
                </div>
              )}
              {displaySubmission.user.city && (
                <div>
                  <strong>{t('submissions.city')}</strong> {displaySubmission.user.city}
                </div>
              )}
            </div>
          </div>
        )}

        {displaySubmission.execution_time_ms != null && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.execution_time_heading') || 'Execution'}
            </div>
            <div className="text-xs text-slate-300">
              <strong>{t('submissions.execution_time')}</strong>{' '}
              {`${displaySubmission.execution_time_ms} ms`}
            </div>
          </div>
        )}

        {isAdminOrJury && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.integrity_title')}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
              <div>
                <strong>{t('submissions.celery_task_id')}</strong>{' '}
                <span className="font-mono text-[11px] text-slate-400">
                  {displaySubmission.celery_task_id || t('common.none')}
                </span>
              </div>
            </div>
          </div>
        )}

        {displayLogs ? (
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {displaySubmission.status === 'completed' || displaySubmission.status === 'failed'
                ? t('submissions.execution_log', 'Execution Log')
                : t('submissions.execution_log_live', 'Execution Log (Live)')}
            </div>
            <pre
              ref={logRef}
              className={`code-panel text-xs font-mono ${
                displaySubmission.status === 'completed'
                  ? 'text-slate-200'
                  : displaySubmission.status === 'failed'
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
              {displayLogs}
            </pre>
          </div>
        ) : null}
      </div>

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
