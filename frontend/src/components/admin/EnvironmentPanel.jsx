import React, { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import InputField from '../ui/InputField';
import Notice from '../ui/Notice';
import QueryErrorState from '../ui/QueryErrorState';
import Skeleton from '../ui/Skeleton';
import ToggleField from '../ui/ToggleField';
import EnvironmentStatus from './EnvironmentStatus';
import ExtendEnvironmentModal from './ExtendEnvironmentModal';
import WorkspaceImagePicker from './WorkspaceImagePicker';
import WorkspaceList from './WorkspaceList';
import { useApp } from '../../context/AppContext';
import { useApiError } from '../../hooks/useApiError';
import {
  useEnvironmentLiveInterval,
  useEnvironmentLiveSubscription,
} from '../../context/EnvironmentLiveContext';
import {
  isEnvironmentHidden,
  useEnvironmentQuery,
  useWorkspaceImagesQuery,
} from '../../hooks/useEnvironmentQuery';
import {
  useExtendEnvironment,
  usePublishEnvironment,
  useSaveEnvironment,
} from '../../hooks/useEnvironmentMutations';
import { formatDateTime, toDateTimeLocal } from '../../utils/formatDate';

const CARD = 'bg-[#0d0e18] border border-white/5 p-5 md:p-8 rounded-2xl animate-fadein';
const NUMBER_FIELDS = ['cpu_cores', 'memory_gib', 'disk_gib'];

function Fact({ label, children }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="text-xs text-slate-200 break-words">{children}</dd>
    </div>
  );
}

/**
 * Environment section of a stage, or of a competition without stages; read-only for the jury.
 * @param {{
 *   challenge: any,
 *   stage?: any,
 *   readOnly?: boolean,
 *   className?: string,
 *   onDirtyChange?: (dirty: boolean) => void,
 *   onExtended?: (endTime: string) => void,
 * }} props
 */
export default function EnvironmentPanel({
  challenge,
  stage = null,
  readOnly = false,
  className = CARD,
  onDirtyChange = undefined,
  onExtended = undefined,
}) {
  const refetchInterval = useEnvironmentLiveInterval(challenge.id);
  const query = useEnvironmentQuery(challenge.id, stage?.id, { refetchInterval });
  // Also while hidden from the jury, so enabling it shows up without a reload
  useEnvironmentLiveSubscription(challenge.id, Boolean(query.data));
  if (!query.data) {
    if (query.isError && isEnvironmentHidden(query.error)) return null;
    if (query.isError) {
      return (
        <div className={className}>
          <QueryErrorState onRetry={query.refetch} minHeight={120} />
        </div>
      );
    }
    return readOnly ? null : (
      <div className={className}>
        <Skeleton count={4} width="100%" height="1rem" />
      </div>
    );
  }
  if (readOnly && !query.data.enabled) return null;
  return (
    <LiveEnvironmentPanel
      env={query.data}
      refetchInterval={refetchInterval}
      challenge={challenge}
      stage={stage}
      readOnly={readOnly}
      className={className}
      onDirtyChange={onDirtyChange}
      onExtended={onExtended}
    />
  );
}

function LiveEnvironmentPanel({
  env,
  refetchInterval,
  challenge,
  stage,
  readOnly,
  className,
  onDirtyChange,
  onExtended,
}) {
  const { t } = useTranslation();
  const { confirm, showToast } = useApp();
  const { showApiError } = useApiError();
  const fieldId = useId();
  const challengeId = challenge.id;
  const stageId = stage?.id ?? null;
  const timezone = challenge.timezone || 'UTC';

  const [edits, setEdits] = useState(/** @type {Record<string, any>} */ ({}));
  const [extending, setExtending] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const save = useSaveEnvironment(challengeId, stageId);
  const publish = usePublishEnvironment(challengeId, stageId);
  const extend = useExtendEnvironment(challengeId, stageId);

  const published = Boolean(env.published_at);
  const editable = !readOnly && !published;
  const value = (key) => (key in edits ? edits[key] : env[key]);
  const enabled = Boolean(value('enabled'));
  const imagesQuery = useWorkspaceImagesQuery(challengeId, !readOnly && (published || enabled));
  const endsAtMs = Date.parse(env.ends_at);
  const original = (key) =>
    key === 'archive_until' ? toDateTimeLocal(env.archive_until) : env[key];
  const dirty = Object.entries(edits).some(
    ([key, next]) => String(next ?? '') !== String(original(key) ?? ''),
  );
  const unsaved = editable && dirty;

  useEffect(() => {
    onDirtyChange?.(unsaved);
  }, [onDirtyChange, unsaved]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  // Re-render once the window closes, so Extend disappears when the backend would refuse it
  useEffect(() => {
    const remaining = endsAtMs - Date.now();
    if (Number.isNaN(remaining) || remaining <= 0 || remaining > 2 ** 31 - 1) return undefined;
    const timer = setTimeout(() => setNowMs(Date.now()), remaining + 50);
    return () => clearTimeout(timer);
  }, [endsAtMs]);

  const setField = (key, next) => setEdits((prev) => ({ ...prev, [key]: next }));
  const images = imagesQuery.data;
  const defaultImageId = images?.find((image) => image.default)?.image_id || images?.[0]?.image_id;
  const imageId = value('image_id') || defaultImageId || '';
  const gpu = value('compute_kind') === 'GPU';
  const state = env.status?.state;
  const canPublish = state === 'ready' && !dirty;
  const canExtend = !readOnly && published && nowMs < endsAtMs;

  const handleSave = async (e) => {
    e.preventDefault();
    if (save.isPending) return;
    const body = {
      enabled,
      auto_publish: Boolean(value('auto_publish')),
      compute_kind: gpu ? 'GPU' : 'CPU',
      cpu_cores: Number(value('cpu_cores')),
      memory_gib: Number(value('memory_gib')),
      disk_gib: Number(value('disk_gib')),
      gpu_type: gpu ? String(value('gpu_type') || '').trim() || null : null,
      image_id: imageId,
    };
    // The backend keeps its default archive date unless the admin picked another one
    if (edits.archive_until) body.archive_until = edits.archive_until;
    try {
      const saved = await save.mutateAsync(body);
      setEdits({});
      showToast(t(saved.enabled ? 'environment.saved' : 'environment.saved_off'));
    } catch (error) {
      showApiError(error, 'environment.save_failed');
    }
  };

  const handlePublish = async () => {
    const ok = await confirm({
      title: t('environment.publish_confirm_title'),
      message: t('environment.publish_confirm', {
        start: formatDateTime(env.starts_at, timezone),
      }),
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
      onExtended?.(body.end_time);
      showToast(t('environment.extended'));
    } catch (error) {
      showApiError(error, 'environment.extend_failed');
    }
  };

  const folders = (env.folders || []).filter(Boolean);
  const imageName = images?.find((image) => image.image_id === env.image_id)?.name || env.image_id;
  const commonFacts = (
    <>
      <Fact label={t('environment.window')}>
        {t('environment.window_value', {
          start: formatDateTime(env.starts_at, timezone),
          end: formatDateTime(env.ends_at, timezone),
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
    </>
  );

  return (
    <div className={className} data-testid="environment-panel">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-white">{t('environment.title')}</h3>
          <p className="text-xs text-slate-400 mt-1">{t('environment.intro')}</p>
        </div>
        <EnvironmentStatus status={env.status} />
      </div>

      {editable ? (
        <form onSubmit={handleSave} className="flex flex-col gap-4">
          <ToggleField
            id={`${fieldId}-enabled`}
            label={t('environment.enabled')}
            checked={enabled}
            onChange={(e) => setField('enabled', e.target.checked)}
          />
          {enabled && (
            <>
              <WorkspaceImagePicker
                images={images}
                loadFailed={imagesQuery.isError}
                value={imageId}
                onChange={(next) => setField('image_id', next)}
              />
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {NUMBER_FIELDS.map((key) => (
                  <InputField
                    key={key}
                    label={t(`environment.${key}`)}
                    type="number"
                    value={String(value(key) ?? '')}
                    onChange={(e) => setField(key, e.target.value)}
                    required
                  />
                ))}
              </div>
              <ToggleField
                id={`${fieldId}-gpu`}
                label={t('environment.gpu')}
                checked={gpu}
                onChange={(e) => setField('compute_kind', e.target.checked ? 'GPU' : 'CPU')}
              />
              {gpu && (
                <InputField
                  label={t('environment.gpu_type')}
                  value={value('gpu_type') || ''}
                  onChange={(e) => setField('gpu_type', e.target.value)}
                  required
                />
              )}
              <ToggleField
                id={`${fieldId}-auto`}
                label={t('environment.auto_publish')}
                checked={Boolean(value('auto_publish'))}
                onChange={(e) => setField('auto_publish', e.target.checked)}
              />
              <InputField
                label={t('environment.archive_until')}
                type="datetime-local"
                value={
                  'archive_until' in edits
                    ? edits.archive_until
                    : toDateTimeLocal(env.archive_until)
                }
                onChange={(e) => setField('archive_until', e.target.value)}
                hint={t('environment.archive_until_hint', { timezone })}
              />
              <dl className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-3">{commonFacts}</dl>
            </>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" isLoading={save.isPending} disabled={!dirty}>
              {t('environment.save')}
            </Button>
            {env.id && env.enabled && (
              <>
                <Button
                  variant="accent"
                  onClick={handlePublish}
                  isLoading={publish.isPending}
                  disabled={!canPublish}
                >
                  {t('environment.publish')}
                </Button>
                {!canPublish && (
                  <span className="text-[11px] text-slate-400">
                    {dirty
                      ? t('environment.publish_save_first')
                      : t('environment.publish_wait_ready')}
                  </span>
                )}
              </>
            )}
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-4">
          {published && !readOnly && <Notice>{t('environment.locked_notice')}</Notice>}
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <Fact label={t('environment.image')}>{imageName || '—'}</Fact>
            <Fact label={t('environment.resources')}>
              {t('environment.resources_value', {
                cpu: env.cpu_cores,
                memory: env.memory_gib,
                disk: env.disk_gib,
              })}
              {env.compute_kind === 'GPU' &&
                `, ${t('environment.resources_gpu', { type: env.gpu_type || '—' })}`}
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
            {commonFacts}
          </dl>
          {canExtend && (
            <div>
              <Button variant="secondary" onClick={() => setExtending(true)}>
                {t('environment.extend')}
              </Button>
            </div>
          )}
        </div>
      )}

      {env.id && env.enabled && (
        <div className="border-t border-white/5 pt-4 mt-5">
          <WorkspaceList
            challengeId={challengeId}
            environmentId={env.id}
            timezone={timezone}
            refetchInterval={refetchInterval}
          />
        </div>
      )}

      {extending && (
        <ExtendEnvironmentModal
          currentEnd={(stage || challenge).end_time}
          timezone={timezone}
          isPending={extend.isPending}
          onClose={() => setExtending(false)}
          onSubmit={handleExtend}
        />
      )}
    </div>
  );
}
