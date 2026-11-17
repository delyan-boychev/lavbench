import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Notice from '../ui/Notice';
import EnvironmentStatus from './EnvironmentStatus';
import ExtendEnvironmentModal from './ExtendEnvironmentModal';
import WorkspaceList from './WorkspaceList';
import { useApp } from '../../context/AppContext';
import { useApiError } from '../../hooks/useApiError';
import { useExtendEnvironment, usePublishEnvironment } from '../../hooks/useEnvironmentMutations';
import { formatDateTime } from '../../utils/formatDate';

function Fact({ label, children }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="text-xs text-slate-200 break-words">{children}</dd>
    </div>
  );
}

/** The admin's next step for each status, as a key under environment.view.hint. */
function hintKey(env) {
  const state = env.status?.state;
  if (!env.enabled || state === 'off') return 'off';
  if (state === 'ready') {
    if (env.published_at) return 'published';
    return env.auto_publish ? 'ready_auto' : 'ready';
  }
  if (state === 'preparing' && env.published_at) return 'preparing_published';
  return state || 'unknown';
}

/**
 * Status and actions of one stage's environment, or the competition's; read-only for the jury.
 * @param {{
 *   env: any,
 *   challenge: any,
 *   imageName: string,
 *   readOnly: boolean,
 *   refetchInterval?: number | false,
 * }} props
 */
export default function EnvironmentCard({ env, challenge, imageName, readOnly, refetchInterval }) {
  const { t } = useTranslation();
  const { confirm, showToast } = useApp();
  const { showApiError } = useApiError();
  const [extending, setExtending] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const publish = usePublishEnvironment(challenge.id);
  const extend = useExtendEnvironment(challenge.id);
  const timezone = challenge.timezone || 'UTC';
  const published = Boolean(env.published_at);
  const endsAtMs = Date.parse(env.ends_at);
  const owner = challenge.stages?.find((stage) => stage.id === env.stage_id) || challenge;

  // Re-render once the window closes, so Extend disappears when the backend would refuse it
  useEffect(() => {
    const remaining = endsAtMs - Date.now();
    if (Number.isNaN(remaining) || remaining <= 0 || remaining > 2 ** 31 - 1) return undefined;
    const timer = setTimeout(() => setNowMs(Date.now()), remaining + 50);
    return () => clearTimeout(timer);
  }, [endsAtMs]);

  const canPublish = !readOnly && env.enabled && !published && env.status?.state === 'ready';
  const canExtend = !readOnly && env.enabled && published && nowMs < endsAtMs;

  const handlePublish = async () => {
    const ok = await confirm({
      title: t('environment.publish_confirm_title'),
      message: t('environment.publish_confirm', { start: formatDateTime(env.starts_at, timezone) }),
      confirmText: t('environment.publish_confirm_button'),
    });
    if (!ok) return;
    try {
      await publish.mutateAsync(env.id);
      showToast(t('environment.published'));
    } catch (error) {
      showApiError(error, 'environment.publish_failed');
    }
  };

  const handleExtend = async (body) => {
    try {
      await extend.mutateAsync({ environmentId: env.id, ...body });
      setExtending(false);
      showToast(t('environment.extended'));
    } catch (error) {
      showApiError(error, 'environment.extend_failed');
    }
  };

  const folders = (env.folders || []).filter(Boolean);

  return (
    <div
      className="flex flex-col gap-4 border-t border-white/5 pt-5"
      data-testid="environment-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="text-sm font-bold text-white">
          {env.stage_title || t('environment.view.competition')}
        </h3>
        <EnvironmentStatus status={env.status} />
      </div>
      {!readOnly && <Notice>{t(`environment.view.hint.${hintKey(env)}`)}</Notice>}
      {env.enabled && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">
          <Fact label={t('environment.window')}>
            {t('environment.window_value', {
              start: formatDateTime(env.starts_at, timezone),
              end: formatDateTime(env.ends_at, timezone),
            })}
          </Fact>
          <Fact label={t('environment.image')}>{imageName || env.image_id || '—'}</Fact>
          <Fact label={t('environment.resources')}>
            {t('environment.resources_value', {
              cpu: env.cpu_cores,
              memory: env.memory_gib,
              disk: env.disk_gib,
            })}
          </Fact>
          <Fact label={t('environment.setting.disk_title')}>
            {t('environment.setting.disk_line', {
              workspace: env.workspace_gib,
              data: env.data_gib,
              disk: env.disk_gib,
            })}
          </Fact>
          <Fact label={t('environment.places')}>
            {t('environment.places_value', { places: env.max_attendance })}
          </Fact>
          <Fact label={t('environment.folders')}>
            {folders.length > 0
              ? folders.map((folder) => `${folder}/`).join(', ')
              : t('environment.no_folders')}
          </Fact>
          <Fact label={t('environment.published_label')}>
            {published
              ? formatDateTime(env.published_at, timezone)
              : env.auto_publish
                ? t('environment.auto_publish_on')
                : t('environment.not_published')}
          </Fact>
          <Fact label={t('environment.archive_until')}>
            {formatDateTime(env.archive_until, timezone)}
          </Fact>
        </dl>
      )}
      {(canPublish || canExtend) && (
        <div className="flex flex-wrap items-center gap-3">
          {canPublish && (
            <Button variant="accent" onClick={handlePublish} isLoading={publish.isPending}>
              {t('environment.publish')}
            </Button>
          )}
          {canExtend && (
            <Button variant="secondary" onClick={() => setExtending(true)}>
              {t('environment.extend')}
            </Button>
          )}
        </div>
      )}
      {env.id && env.enabled && (
        <WorkspaceList
          challengeId={challenge.id}
          environmentId={env.id}
          timezone={timezone}
          refetchInterval={refetchInterval}
        />
      )}
      {extending && (
        <ExtendEnvironmentModal
          currentEnd={owner.end_time}
          timezone={timezone}
          isPending={extend.isPending}
          onClose={() => setExtending(false)}
          onSubmit={handleExtend}
        />
      )}
    </div>
  );
}
