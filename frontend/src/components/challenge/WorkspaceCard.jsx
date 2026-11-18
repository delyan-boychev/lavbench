import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink, Laptop } from 'lucide-react';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import Notice from '../ui/Notice';
import { useApiError } from '../../hooks/useApiError';
import { useRetryAfter } from '../../hooks/useRetryAfter';
import {
  useEnvironmentLiveInterval,
  useEnvironmentLiveSubscription,
} from '../../context/EnvironmentLiveContext';
import { isEnvironmentHidden, useTaskEnvironmentQuery } from '../../hooks/useEnvironmentQuery';
import { useLaunchWorkspace } from '../../hooks/useEnvironmentMutations';
import { formatDateTime } from '../../utils/formatDate';
import { openWorkspaceWindow, postLaunchForm } from '../../utils/workspaceLaunch';

const STATES = new Set(['not_open', 'preparing', 'ready', 'unknown', 'closed']);
const OPENABLE = new Set(['ready', 'unknown']);
const MAX_TIMER_MS = 2 ** 31 - 1;
// After the end the card re-checks until the server reports it closed (client clocks drift)
const CLOSE_RECHECK_MS = 5_000;
const CLOSE_RECHECKS = 12;

/**
 * The student's workspace card; nothing renders until the API reports an environment.
 * Without workspaces on the competition it makes no request and opens no stream.
 * @param {{ task: { id: string, challenge_id: string }, enabled: boolean, timezone?: string }} props
 */
export default function WorkspaceCard({ task, enabled, timezone = 'UTC' }) {
  const refetchInterval = useEnvironmentLiveInterval(task.challenge_id);
  const { data, error, refetch } = useTaskEnvironmentQuery(task.challenge_id, task.id, {
    refetchInterval,
    enabled,
  });
  // A stage without an environment (409) still listens, so enabling it shows the card
  const listening =
    Boolean(data) || /** @type {any} */ (error)?.code === 'ERR_ENVIRONMENT_NOT_ENABLED';
  useEnvironmentLiveSubscription(task.challenge_id, enabled && listening);
  if (!enabled || !data || !STATES.has(data.status) || isEnvironmentHidden(error)) return null;
  return <LiveWorkspaceCard task={task} env={data} refetch={refetch} timezone={timezone} />;
}

/** The card's one line: when it opens or closes, or what is happening now. */
function stateLine(env, t, timezone) {
  // Past its start but not published: the badge says "Not open yet" and no past time is shown
  if (env.status === 'not_open' && env.overdue) return '';
  const start = formatDateTime(env.starts_at, timezone);
  const end = formatDateTime(env.ends_at, timezone);
  return t(`environment.card.hint_${env.status}`, { start, end });
}

function LiveWorkspaceCard({ task, env, refetch, timezone }) {
  const { t } = useTranslation();
  const { showApiError } = useApiError();
  const launch = useLaunchWorkspace();
  const { waiting, wait } = useRetryAfter();
  const [popupBlocked, setPopupBlocked] = useState(false);

  const status = env.status;
  const endsAtMs = Date.parse(env.ends_at);
  const folder = OPENABLE.has(status) && env.folder_name;
  const line = stateLine(env, t, timezone);

  // The end is not signalled by the stream, so the card re-checks until the server says closed
  useEffect(() => {
    if (status === 'closed' || Number.isNaN(endsAtMs)) return undefined;
    const remaining = endsAtMs - Date.now();
    if (remaining > MAX_TIMER_MS) return undefined;
    let checks = 0;
    let timer;
    const check = () => {
      refetch();
      checks += 1;
      if (checks < CLOSE_RECHECKS) timer = setTimeout(check, CLOSE_RECHECK_MS);
    };
    timer = setTimeout(check, Math.max(0, remaining) + 1000);
    return () => clearTimeout(timer);
  }, [status, endsAtMs, refetch]);

  const handleOpen = async () => {
    const opened = openWorkspaceWindow(t('environment.card.opening'));
    // Without its own tab the launch would replace LavBench, so nothing is requested
    setPopupBlocked(!opened.win);
    if (!opened.win) return;
    try {
      const result = await launch.mutateAsync(task.id);
      if (opened.win.closed) return;
      postLaunchForm(result);
    } catch (error) {
      if (opened.fresh) opened.win.close();
      showApiError(error, 'environment.card.launch_failed');
      wait(error);
      if (error?.status === 409 || error?.status === 503) refetch();
    }
  };

  return (
    <div className="surface" style={{ padding: '16px 20px' }} data-testid="workspace-card">
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            minWidth: 0,
            flex: '1 1 260px',
          }}
        >
          <Laptop
            size={18}
            aria-hidden="true"
            style={{ color: 'var(--accent)', flexShrink: 0, marginTop: 2 }}
          />
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
              <h2 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {t('environment.card.title')}
              </h2>
              <Badge status={`env_${status}`} />
            </div>
            {(folder || line) && (
              <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                {folder && (
                  <>
                    {t('environment.card.folder')}{' '}
                    <code style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {env.folder_name}/
                    </code>
                    {line && ' · '}
                  </>
                )}
                {line}
              </p>
            )}
            {waiting && (
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                {t('environment.card.retry_wait')}
              </p>
            )}
            {popupBlocked && (
              <Notice tone="warning" role="alert" className="mt-2">
                {t('environment.card.popup_blocked')}
              </Notice>
            )}
          </div>
        </div>
        {status !== 'closed' && (
          <Button
            variant="accent"
            onClick={handleOpen}
            isLoading={launch.isPending}
            disabled={!OPENABLE.has(status) || waiting}
            aria-label={t('environment.card.open_new_tab')}
          >
            {t('environment.card.open')}
            <ExternalLink size={14} aria-hidden="true" />
          </Button>
        )}
      </div>
    </div>
  );
}
