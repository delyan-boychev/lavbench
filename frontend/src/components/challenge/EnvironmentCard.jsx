import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Server } from 'lucide-react';
import Button from '../ui/Button';
import { useApp } from '../../context/AppContext';
import EnvironmentService, {
  openLabWindow,
  postLaunchForm,
} from '../../services/EnvironmentService';

const POLL_MS = { preparing: 10_000, not_started: 30_000, ready: 30_000, blocked: 30_000 };

function StageEnvironment({ challengeId, stage }) {
  const { t } = useTranslation();
  const { showToast } = useApp();
  const [launching, setLaunching] = useState(false);

  const { data } = useQuery({
    queryKey: ['environment', challengeId, stage.id],
    queryFn: () => EnvironmentService.getEnvironment(challengeId, stage.id),
    refetchInterval: (query) => {
      const result = query.state.data?.data;
      if (!result) return 15_000;
      const retry = result.retry_after_seconds ? result.retry_after_seconds * 1000 : null;
      return retry || POLL_MS[result.status] || false;
    },
  });
  const status = data?.data?.status || 'unavailable';

  const handleLaunch = async () => {
    const labWindow = openLabWindow();
    setLaunching(true);
    try {
      const res = await EnvironmentService.launchEnvironment(challengeId, stage.id);
      if (!res.ok) {
        labWindow?.close();
        showToast(
          t(`api.${res.data?.code}`, res.data?.error || t('environment.launch_failed')),
          'error',
        );
        return;
      }
      postLaunchForm(res.data, labWindow);
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div
      className="surface"
      style={{ padding: '18px 22px', display: 'flex', alignItems: 'center', gap: 16 }}
      data-testid={`environment-${stage.id}`}
    >
      <Server size={18} style={{ color: 'var(--accent)', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
          {t('environment.title', { stage: stage.title })}
        </div>
        <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          {t(`environment.status.${status}`)}
        </div>
      </div>
      <Button
        variant="accent"
        onClick={handleLaunch}
        disabled={status !== 'ready'}
        isLoading={launching}
      >
        {t('environment.get_button')}
      </Button>
    </div>
  );
}

export default function EnvironmentCard({ challenge }) {
  const stages = (challenge?.stages || []).filter((stage) => stage.compute_enabled);
  if (stages.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {stages
        .sort((a, b) => a.stage_number - b.stage_number)
        .map((stage) => (
          <StageEnvironment key={stage.id} challengeId={challenge.id} stage={stage} />
        ))}
    </div>
  );
}
