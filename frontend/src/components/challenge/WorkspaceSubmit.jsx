import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Send } from 'lucide-react';
import Button from '../ui/Button';
import { useApp } from '../../context/AppContext';
import EnvironmentService from '../../services/EnvironmentService';

export default function WorkspaceSubmit({ task }) {
  const { t } = useTranslation();
  const { showToast } = useApp();
  const queryClient = useQueryClient();
  const [lastResult, setLastResult] = useState(null);

  const submitMutation = useMutation({
    mutationFn: (/** @type {string} */ taskId) => EnvironmentService.submitFromWorkspace(taskId),
  });

  const handleSubmit = async () => {
    const res = await submitMutation.mutateAsync(task.id);
    if (!res.ok) {
      showToast(
        t(`api.${res.data?.code}`, res.data?.error || t('environment.submit_failed')),
        'error',
      );
      return;
    }
    setLastResult(res.data);
    showToast(t('environment.submit_success'), 'emerald');
    queryClient.invalidateQueries({ queryKey: ['submissions'] });
  };

  return (
    <div className="surface" style={{ padding: '22px 26px' }} data-testid="workspace-submit">
      <h3 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: 6 }}>
        {t('environment.submit_title')}
      </h3>
      <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: 14 }}>
        {t('environment.submit_desc', { path: task.workspace_submission_path })}
      </p>
      <Button onClick={handleSubmit} isLoading={submitMutation.isPending}>
        <Send size={14} />
        {t('environment.submit_button')}
      </Button>
      {lastResult && (
        <p
          style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 12 }}
          data-testid="workspace-submit-result"
        >
          {t('environment.submit_receipt', {
            size: lastResult.export.csv_size,
            sha: lastResult.export.csv_sha256.slice(0, 12),
          })}
        </p>
      )}
    </div>
  );
}
