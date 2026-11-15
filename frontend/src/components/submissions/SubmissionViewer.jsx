import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import Badge from '../ui/Badge';
import CodePreview from '../ui/CodePreview';
import EmptyState from '../ui/EmptyState';
import { Star } from 'lucide-react';
import ToggleField from '../ui/ToggleField';
import useSSE from '../../hooks/useSSE';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import { appendCappedLog } from '../../utils/logBuffer';
import { formatScore } from '../../utils/formatScore';
import Notice from '../ui/Notice';

// Live log lines are batched so a chatty submission does not re-render once per line
const LOG_FLUSH_MS = 250;

function parseCells(codeCells) {
  let cells;
  try {
    cells = typeof codeCells === 'string' ? JSON.parse(codeCells) : codeCells || [];
  } catch {
    cells = [];
  }
  return (Array.isArray(cells) ? cells : []).map((cell) =>
    typeof cell === 'string' ? { type: 'code', source: cell } : cell,
  );
}

function SubmissionViewer({
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
  // Parents key the viewer by submission id, so this state never leaks between submissions
  const [liveLogs, setLiveLogs] = useState('');
  const logRef = useRef(null);
  const pendingLogRef = useRef('');
  const flushTimerRef = useRef(null);
  const lastFlushRef = useRef(0);

  const cancelLogFlush = useCallback(() => {
    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
  }, []);

  const flushLogs = useCallback(() => {
    cancelLogFlush();
    lastFlushRef.current = Date.now();
    const chunk = pendingLogRef.current;
    if (!chunk) return;
    pendingLogRef.current = '';
    setLiveLogs((prev) => appendCappedLog(prev, chunk));
  }, [cancelLogFlush]);

  // Leading flush shows the first line immediately; later lines wait for the trailing flush
  const queueLogLine = useCallback(
    (line) => {
      pendingLogRef.current += line + '\n';
      if (flushTimerRef.current !== null) return;
      const wait = LOG_FLUSH_MS - (Date.now() - lastFlushRef.current);
      if (wait <= 0) {
        flushLogs();
      } else {
        flushTimerRef.current = setTimeout(flushLogs, wait);
      }
    },
    [flushLogs],
  );

  useEffect(() => cancelLogFlush, [cancelLogFlush]);

  const submissionId = submission?.id;
  const isTerminal = submission?.status === 'completed' || submission?.status === 'failed';
  // Finished submissions show the stored log from the REST detail
  const displayLogs = isTerminal ? submission?.logs || liveLogs : liveLogs || submission?.logs;

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTo({
        top: logRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [liveLogs, submission?.logs]);

  // Only a running submission has a live log; a queued one opens the stream once the
  // parent's poll sees it start, and a finished one is never replayed over SSE
  const streamUrl =
    submission?.status === 'running' ? `/api/submissions/${submissionId}/logs/live` : '';
  useSSE(streamUrl, {
    // The server replays logs then sends the final status and closes the stream
    isTerminal: (data) => data.status === 'completed' || data.status === 'failed',
    onMessage: (data) => {
      if (data.info === 'connected') {
        // Every connection, including the browser's own reconnect, replays the whole log
        cancelLogFlush();
        pendingLogRef.current = '';
        setLiveLogs('');
      } else if (data.log) {
        queueLogLine(data.log);
      } else if (data.status) {
        flushLogs();
        if (data.status === 'completed' || data.status === 'failed') {
          onSubmissionUpdate?.(submissionId);
        }
      }
    },
  });

  const cells = useMemo(() => parseCells(submission?.code_cells), [submission?.code_cells]);

  if (!submission) {
    return (
      <EmptyState
        minHeight={300}
        message={t('submissions.select_to_view')}
        icon={<FileText size={32} className="text-slate-500" />}
      />
    );
  }

  const isCompetitor = currentUser?.role === 'competitor';
  const isAdminOrJury = currentUser?.role === 'admin' || currentUser?.role === 'jury';
  const showUserDemographics =
    isAdminOrJury && submission.user && (submission.user.name || submission.user.username);

  return (
    <div className="flex flex-col gap-4">
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
              {submission.is_baseline && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400 inline-flex items-center gap-1">
                  {t('submissions.baseline_label')}
                </span>
              )}
              {submission.is_final_selection && (
                <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-400 inline-flex items-center gap-1">
                  <Star className="w-3 h-3" />
                  {t('submissions.final_selection_star')}
                </span>
              )}
              {(submission.status === 'queued' || submission.status === 'running') &&
                (currentUser?.role === 'admin' ||
                  currentUser?.role === 'jury' ||
                  (currentUser?.role === 'competitor' &&
                    submission.user?.id === currentUser?.id)) && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onKill && onKill(submission.id);
                    }}
                    disabled={killing}
                    className="text-xs font-semibold px-3 py-1 rounded-lg border border-rose-600 bg-rose-600/20 text-rose-300 hover:bg-rose-600/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {killing ? '...' : t('submissions.kill')}
                  </button>
                )}
            </div>

            {submission.detailed_status === 'failed_infra' && (
              <Notice tone="warning" className="mb-2">
                {t('submissions.failed_infra_note')}
              </Notice>
            )}

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
                  {formatScore(submission.public_score)}
                </div>
              </div>
            )}
            {submission.private_score != null && (
              <div className="text-right">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                  {t('submissions.private_score')}
                </div>
                <div className="font-mono text-base font-bold text-emerald-400">
                  {formatScore(submission.private_score)}
                </div>
              </div>
            )}
          </div>
        </div>

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

        {submission.execution_time_ms != null && (
          <div className="mb-4 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              {t('submissions.execution_time_heading') || 'Execution'}
            </div>
            <div className="text-xs text-slate-300">
              <strong>{t('submissions.execution_time')}</strong>{' '}
              {`${submission.execution_time_ms} ms`}
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
                  {submission.celery_task_id || t('common.none')}
                </span>
              </div>
            </div>
          </div>
        )}

        {displayLogs ? (
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

export default React.memo(SubmissionViewer);
