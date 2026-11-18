import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileText, Upload } from 'lucide-react';
import Button from '../ui/Button';
import FileDropZone from '../ui/FileDropZone';
import Notice from '../ui/Notice';
import TaskService from '../../services/TaskService';
import { requireOk } from '../../services/apiResult';
import { useApp } from '../../context/AppContext';
import { useApiErrorText } from '../../hooks/useApiError';
import { useRetryAfter } from '../../hooks/useRetryAfter';

const SUBMISSION_FILE = 'submission.parquet';
const NOTEBOOK_FILE = 'solution.ipynb';

/** One of the two files of the emergency upload. */
function FilePick({ name, accept, file, onPick, disabled }) {
  const { t } = useTranslation();
  return (
    <FileDropZone
      className="file-drop-zone"
      accept={accept}
      onFiles={([picked]) => !disabled && onPick(picked)}
    >
      <div
        className="pointer-events-none"
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}
      >
        {file ? (
          <span
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: '0.8125rem',
              fontWeight: 600,
              color: 'var(--accent)',
            }}
          >
            <FileText size={14} aria-hidden="true" />
            {file.name}
          </span>
        ) : (
          <>
            <Upload size={20} aria-hidden="true" style={{ color: 'var(--text-muted)' }} />
            <code style={{ fontSize: '0.8125rem', color: 'var(--text-primary)' }}>{name}</code>
          </>
        )}
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {file ? t('challenge.click_to_replace') : t('challenge.click_or_drag')}
        </span>
      </div>
    </FileDropZone>
  );
}

/**
 * The student's submit card for a file task: Submit reads submission.parquet and
 * solution.ipynb from the workspace; while the admin allows it, the two files can be uploaded.
 * @param {{ task: any, challenge: any }} props
 */
export default function FileSubmit({ task, challenge }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useApp();
  const formatApiError = useApiErrorText();
  const { secondsLeft, waiting, wait } = useRetryAfter();
  const [error, setError] = useState('');
  const [parquet, setParquet] = useState(null);
  const [notebook, setNotebook] = useState(null);

  const onSuccess = (res) => {
    setError('');
    showToast(t('challenge.submission_queued'));
    queryClient.invalidateQueries({ queryKey: ['submissions', task.id] });
    navigate(`/challenges/${challenge.id}/submissions`, {
      state: { submissionId: res.data?.submission_id },
    });
  };
  const onError = (err) => {
    setError(formatApiError(err, 'challenge.submission_failed'));
    wait(err);
  };

  const fromWorkspace = useMutation({
    mutationFn: async () => requireOk(await TaskService.submitWorkspace(task.id)),
    onSuccess,
    onError,
  });
  const upload = useMutation({
    mutationFn: async () => requireOk(await TaskService.submitFile(task.id, parquet, notebook)),
    onSuccess,
    onError,
  });
  const busy = fromWorkspace.isPending || upload.isPending;
  const folder = task.folder_name || '';

  return (
    <div
      className="surface"
      style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 16 }}
      data-testid="file-submit"
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {t('challenge.submit_solution')}
        </h3>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {t('challenge.submissions_day_limit', { count: challenge.max_eval_requests })}
        </span>
      </div>

      <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
        {t('challenge.file_submit.explain', {
          file: SUBMISSION_FILE,
          notebook: NOTEBOOK_FILE,
          folder,
        })}
      </p>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
        <Button
          variant="accent"
          onClick={() => fromWorkspace.mutate()}
          isLoading={fromWorkspace.isPending}
          disabled={busy || waiting}
        >
          {fromWorkspace.isPending
            ? t('challenge.file_submit.reading')
            : t('challenge.file_submit.submit')}
        </Button>
        {waiting && (
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }} aria-live="polite">
            {t('challenge.file_submit.retry_in', { count: secondsLeft })}
          </span>
        )}
      </div>

      {error && (
        <Notice tone="error" role="alert">
          {error}
        </Notice>
      )}

      {task.emergency_upload_enabled && (
        <div
          style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
          data-testid="emergency-upload-form"
        >
          <Notice tone="warning">{t('challenge.file_submit.emergency_notice')}</Notice>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <FilePick
              name={SUBMISSION_FILE}
              accept=".parquet"
              file={parquet}
              onPick={setParquet}
              disabled={busy}
            />
            <FilePick
              name={NOTEBOOK_FILE}
              accept=".ipynb"
              file={notebook}
              onPick={setNotebook}
              disabled={busy}
            />
          </div>
          <Button
            variant="secondary"
            onClick={() => upload.mutate()}
            isLoading={upload.isPending}
            disabled={!parquet || !notebook || busy || waiting}
          >
            {t('challenge.file_submit.upload')}
          </Button>
        </div>
      )}
    </div>
  );
}
