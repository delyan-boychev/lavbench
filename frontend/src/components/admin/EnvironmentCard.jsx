import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Disclosure from '../ui/Disclosure';
import SummaryList from '../ui/SummaryList';
import EnvironmentStatus from './EnvironmentStatus';
import ExtendEnvironmentModal from './ExtendEnvironmentModal';
import WorkspaceList from './WorkspaceList';
import { useApp } from '../../context/AppContext';
import { useApiError } from '../../hooks/useApiError';
import { useExtendEnvironment, usePublishEnvironment } from '../../hooks/useEnvironmentMutations';
import { useFieldErrors } from '../../hooks/useFieldErrors';
import { formatDateTime } from '../../utils/formatDate';

/** The phase line the backend's `phase` stands for, with its time. */
function phaseLine(env, t, timezone) {
  const at = (iso) => formatDateTime(iso, timezone);
  switch (env.phase) {
    case 'unpublished':
      return env.auto_publish_at
        ? t('environment.view.phase.auto', { date: at(env.auto_publish_at) })
        : t('environment.view.phase.unpublished', { start: at(env.starts_at) });
    case 'published':
      return t('environment.view.phase.published', { start: at(env.starts_at) });
    case 'open':
      return t('environment.view.phase.open', { end: at(env.ends_at) });
    case 'ended':
      return t('environment.view.phase.ended', { end: at(env.ends_at) });
    default:
      return t('environment.view.phase.off');
  }
}

/**
 * Status and actions of one stage's environment, or the competition's; read-only for the jury.
 * @param {{
 *   env: any,
 *   challenge: any,
 *   readOnly: boolean,
 *   refetchInterval?: number | false,
 * }} props
 */
export default function EnvironmentCard({ env, challenge, readOnly, refetchInterval }) {
  const { t } = useTranslation();
  const { confirm, showToast } = useApp();
  const { showApiError } = useApiError();
  const extendErrors = useFieldErrors();
  const [extending, setExtending] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const publish = usePublishEnvironment(challenge.id);
  const extend = useExtendEnvironment(challenge.id);
  const timezone = challenge.timezone || 'UTC';
  const published = Boolean(env.published_at);
  const endsAtMs = Date.parse(env.ends_at);
  const owner = challenge.stages?.find((stage) => stage.id === env.stage_id) || challenge;
  const title = env.stage_title || t('environment.view.competition');

  // Re-render once the window closes, so Extend disappears when the backend would refuse it
  useEffect(() => {
    const remaining = endsAtMs - Date.now();
    if (Number.isNaN(remaining) || remaining <= 0 || remaining > 2 ** 31 - 1) return undefined;
    const timer = setTimeout(() => setNowMs(Date.now()), remaining + 50);
    return () => clearTimeout(timer);
  }, [endsAtMs]);

  const canPublish = !readOnly && env.enabled && !published && env.status?.state === 'ready';
  const canExtend = !readOnly && env.enabled && published && nowMs < endsAtMs;

  const openWindow = t('environment.window_value', {
    start: formatDateTime(env.starts_at, timezone),
    end: formatDateTime(env.ends_at, timezone),
  });
  const image = env.image_name || env.image_id || '—';
  const machine = t('environment.resources_value', {
    cpu: env.cpu_cores,
    memory: env.memory_gib,
    disk: env.disk_gib,
  });
  const folders = (env.folders || []).filter(Boolean);

  const handlePublish = async () => {
    const ok = await confirm({
      title: t('environment.publish_confirm_title', { stage: title }),
      message: (
        <div className="flex flex-col gap-3">
          <SummaryList
            className="grid grid-cols-1 gap-2"
            items={[
              { key: 'image', label: t('environment.image'), value: image },
              { key: 'machine', label: t('environment.setting.profile'), value: machine },
            ]}
          />
          <p>
            {t('environment.publish_confirm', { start: formatDateTime(env.starts_at, timezone) })}
          </p>
        </div>
      ),
      confirmText: t('environment.publish_confirm_button'),
      focusCancel: true,
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
    extendErrors.reset();
    try {
      await extend.mutateAsync({ environmentId: env.id, ...body });
      setExtending(false);
      showToast(t('environment.extended'));
    } catch (error) {
      extendErrors.capture(error);
      showApiError(error, 'environment.extend_failed');
    }
  };

  return (
    <div
      className="flex flex-col gap-4 border-t border-white/5 pt-5"
      data-testid="environment-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0">
          <h3 className="text-sm font-bold text-white">{title}</h3>
          <p className="text-xs text-slate-300" data-testid="environment-phase">
            {phaseLine(env, t, timezone)}
          </p>
        </div>
        <EnvironmentStatus status={env.status} />
      </div>
      {env.enabled && (
        <>
          <SummaryList
            items={[
              { key: 'window', label: t('environment.window'), value: openWindow },
              { key: 'image', label: t('environment.image'), value: image },
              { key: 'machine', label: t('environment.setting.profile'), value: machine },
              { key: 'places', label: t('environment.places'), value: env.max_attendance },
              {
                key: 'folders',
                label: t('environment.folders'),
                value:
                  folders.length > 0
                    ? folders.map((folder) => `${folder}/`).join(', ')
                    : t('environment.no_folders'),
              },
            ]}
          />
          <Disclosure
            label={t('environment.more_options')}
            open={moreOpen}
            onToggle={() => setMoreOpen(!moreOpen)}
          >
            <SummaryList
              items={[
                {
                  key: 'archive',
                  label: t('environment.archive_until'),
                  value: formatDateTime(env.archive_until, timezone),
                },
              ]}
            />
          </Disclosure>
        </>
      )}
      {(canPublish || canExtend) && (
        <div className="flex flex-wrap items-center gap-3">
          {canPublish && (
            <Button variant="accent" onClick={handlePublish} isLoading={publish.isPending}>
              {t('environment.publish')}
            </Button>
          )}
          {canExtend && (
            <Button
              variant="secondary"
              onClick={() => {
                extendErrors.reset();
                setExtending(true);
              }}
            >
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
          errors={extendErrors.errors}
          onFieldEdit={extendErrors.clear}
          onClose={() => setExtending(false)}
          onSubmit={handleExtend}
        />
      )}
    </div>
  );
}
