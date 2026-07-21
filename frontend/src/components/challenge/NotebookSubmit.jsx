import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import ChallengeService from '../../services/ChallengeService';
import TaskService from '../../services/TaskService';
import Button from '../ui/Button';
import CodePreview from '../ui/CodePreview';
import { Book, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export default function NotebookSubmit({ task, challenge }) {
  const { currentUser } = useAuth();
  const { showToast } = useApp();
  const { t } = useTranslation();

  const [cells, setCells] = useState([]);
  const [selectedCellIds, setSelectedCellIds] = useState([]);
  const [fileName, setFileName] = useState('');

  const parseMutation = useMutation({
    mutationFn: (/** @type {any} */ variables) =>
      ChallengeService.parseNotebook(variables.challengeId, variables.file),
  });
  const submitMutation = useMutation({
    mutationFn: (/** @type {any} */ variables) =>
      TaskService.submit(variables.taskId, variables.selected),
  });

  const isCompetitor = currentUser?.role === 'competitor';
  const stage = challenge?.stages?.find((s) => s.id === task?.stage_id);
  const graceMs = (challenge?.deadline_grace_period_seconds || 60) * 1000;
  const stageEnded = stage
    ? new Date().getTime() > new Date(stage.end_time).getTime() + graceMs
    : false;
  const challengeEnded =
    !stage &&
    challenge?.end_time &&
    new Date().getTime() > new Date(challenge.end_time).getTime() + graceMs;
  const isClosed =
    !challenge?.is_active ||
    challenge?.is_archived ||
    challenge?.scores_finalized ||
    challengeEnded ||
    stageEnded;

  // Admin/Jury: show info panel only
  if (!isCompetitor) {
    return (
      <div className="surface" style={{ padding: '22px 26px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'var(--warning)',
              display: 'inline-block',
            }}
          />
          <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--warning)' }}>
            {t('challenge.judge_session_active')}
          </h3>
        </div>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          {t('challenge.judge_session_desc')}
        </p>
      </div>
    );
  }

  if (isClosed) {
    const isFinalized = challenge?.scores_finalized;
    return (
      <div className="surface" style={{ padding: '22px 26px' }}>
        <h3
          style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--danger)', marginBottom: 6 }}
        >
          {stageEnded
            ? t('challenge.stage_submission_closed')
            : isFinalized
              ? t('challenge.competition_finalized')
              : t('challenge.competition_closed')}
        </h3>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          {stageEnded
            ? t('challenge.stage_deadline_passed', { title: stage.title })
            : isFinalized
              ? t('challenge.competition_finalized_desc')
              : t('challenge.competition_closed_desc')}
        </p>
      </div>
    );
  }

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.name.endsWith('.ipynb')) {
      showToast(t('challenge.only_ipynb_supported'), 'error');
      return;
    }
    setSelectedCellIds([]);
    setCells([]);
    try {
      const res = await parseMutation.mutateAsync({ challengeId: challenge.id, file });
      if (res.ok) {
        const parsedCells = res.data.cells || [];
        setCells(parsedCells);
        setFileName(res.data.filename);

        // Auto-select cells containing "# SUBMIT" tag
        const submitTagRegex = /#\s*SUBMIT/i;
        const autoSelectedIds = parsedCells
          .filter((c) => c.type === 'code' && submitTagRegex.test(c.source || ''))
          .map((c) => c.id);

        if (autoSelectedIds.length > 0) {
          setSelectedCellIds(autoSelectedIds);
          showToast(
            t('challenge.parsed_cells_auto_selected', {
              total: parsedCells.length,
              selected: autoSelectedIds.length,
            }),
          );
        } else {
          showToast(
            t('challenge.parsed_cells', { total: parsedCells.length, filename: res.data.filename }),
          );
        }
      } else {
        const errCode = res.data?.code;
        const errMsg = errCode
          ? t(`api.${errCode}`, res.data?.error || t('challenge.failed_parse'))
          : res.data?.error || t('challenge.failed_parse');
        showToast(errMsg, 'error');
      }
    } catch {
      showToast(t('challenge.network_error_parse'), 'error');
    }
  };

  const handleSubmit = async () => {
    if (selectedCellIds.length === 0) {
      showToast(t('challenge.select_cells_to_submit'), 'error');
      return;
    }
    const selected = cells.filter((c) => selectedCellIds.includes(c.id));
    try {
      const res = await submitMutation.mutateAsync({ taskId: task.id, selected });
      if (res.ok) {
        showToast(t('challenge.submission_queued'));
        setCells([]);
        setSelectedCellIds([]);
        setFileName('');
      } else {
        const errData = /** @type {any} */ (res.data);
        const errCode = errData?.code;
        const errMsg = errCode
          ? t(`api.${errCode}`, errData?.error || t('challenge.submission_failed'))
          : errData?.error || t('challenge.submission_failed');
        showToast(errMsg, 'error');
      }
    } catch {
      showToast(t('challenge.network_error_submit'), 'error');
    }
  };

  return (
    <div
      className="surface"
      style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 18 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {t('challenge.submit_solution')}
        </h3>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {t('challenge.submissions_day_limit', { count: challenge.max_eval_requests })}
        </span>
      </div>

      {/* Upload zone */}
      <label className="file-drop-zone">
        <input type="file" accept=".ipynb" className="sr-only" onChange={handleUpload} />
        {parseMutation.isPending ? (
          <div
            className="pointer-events-none"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              color: 'var(--text-secondary)',
            }}
          >
            <div
              className="animate-spin"
              style={{
                width: 16,
                height: 16,
                border: '2px solid var(--border)',
                borderTopColor: 'var(--accent)',
                borderRadius: '50%',
              }}
            />
            {t('challenge.parsing_notebook')}
          </div>
        ) : fileName ? (
          <div
            className="pointer-events-none"
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}
          >
            <span
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: 'var(--accent)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.375rem',
              }}
            >
              <Book className="w-4 h-4" />
              {fileName}
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {t('challenge.click_to_replace')}
            </span>
          </div>
        ) : (
          <div
            className="pointer-events-none"
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}
          >
            <Upload size={28} style={{ color: 'var(--text-muted)' }} />
            <span
              style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', fontWeight: 600 }}
            >
              {t('challenge.upload_jupyter_notebook')}
            </span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {t('challenge.click_or_drag')}
            </span>
          </div>
        )}
      </label>

      {/* Cell picker */}
      {cells.length > 0 && (
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 10,
            }}
          >
            <h4
              style={{
                fontSize: '0.8rem',
                fontWeight: 700,
                color: 'var(--text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {t('challenge.select_cells_count', {
                selected: selectedCellIds.length,
                total: cells.filter((c) => c.type === 'code').length,
              })}
            </h4>
            <button
              onClick={() =>
                setSelectedCellIds(cells.filter((c) => c.type === 'code').map((c) => c.id))
              }
              className="btn btn-secondary"
            >
              {t('challenge.select_all_code')}
            </button>
          </div>
          <div
            style={{
              maxHeight: 500,
              overflowY: 'auto',
            }}
          >
            <CodePreview
              cells={cells}
              selectable={true}
              selectedIds={selectedCellIds}
              onSelectionChange={setSelectedCellIds}
              defaultCollapsed={false}
              maxHeight="300px"
            />
          </div>
        </div>
      )}

      {/* Submit */}
      {cells.length > 0 && (
        <Button
          onClick={handleSubmit}
          disabled={submitMutation.isPending || selectedCellIds.length === 0}
          size="lg"
          className="w-full"
        >
          {submitMutation.isPending ? (
            <>
              <div
                className="animate-spin"
                style={{
                  width: 14,
                  height: 14,
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: '#fff',
                  borderRadius: '50%',
                }}
              />
              {t('challenge.submitting')}
            </>
          ) : (
            t('challenge.submit_cells_for_evaluation', { count: selectedCellIds.length })
          )}
        </Button>
      )}
    </div>
  );
}
