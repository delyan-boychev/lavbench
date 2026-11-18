import React, { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Disclosure from '../ui/Disclosure';
import InputField from '../ui/InputField';
import Notice from '../ui/Notice';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import WorkspaceImagePicker from './WorkspaceImagePicker';
import { useGuide } from '../../context/GuideContext';
import { workspacesOffered } from '../../hooks/useEnvironmentQuery';
import { diskSummary, settingLocked, withCatalogDefaults } from '../../utils/workspaceSetting';

// The admin guide's "## 10. Student Workspaces" section, in every language
const GUIDE_SECTION = '10';

/**
 * The "Student workspaces" section of the competition create and edit forms, saved with them.
 * @param {{
 *   draft: import('../../utils/workspaceSetting').WorkspaceDraft,
 *   onChange: (draft: import('../../utils/workspaceSetting').WorkspaceDraft) => void,
 *   catalog: { data?: any, isError: boolean, error: unknown, refetch?: () => void },
 *   timezone: string,
 *   environments?: any[],
 *   errors?: Record<string, string>,
 *   onFieldEdit?: (field: string) => void,
 * }} props
 */
export default function WorkspaceSettingsSection({
  draft,
  onChange,
  catalog,
  timezone,
  environments = [],
  errors = /** @type {Record<string, string>} */ ({}),
  onFieldEdit = undefined,
}) {
  const { t } = useTranslation();
  const { openGuide } = useGuide();
  const fieldId = useId();
  const [moreOpen, setMoreOpen] = useState(() => Boolean(draft.archive_until));
  const data = catalog.data;

  // Empty choices take the catalog's defaults once it arrives
  useEffect(() => {
    if (!data || !draft.enabled) return;
    const filled = withCatalogDefaults(draft, data);
    if (Object.keys(filled).some((key) => filled[key] !== draft[key])) onChange(filled);
  }, [data, draft, onChange]);

  if (!workspacesOffered(catalog)) return null;

  const set = (key, value) => {
    onFieldEdit?.(key);
    onChange({ ...draft, [key]: value });
  };
  const locked = settingLocked(environments);
  const profiles = data?.profiles || [];
  const profileOptions = profiles.map((profile) => ({
    value: profile.id,
    label: t('environment.setting.profile_option', {
      name: profile.name,
      cpu: profile.cpu_cores,
      memory: profile.memory_gib,
    }),
  }));
  // A stored profile nanoColab no longer lists stays visible instead of silently changing
  if (draft.profile_id && !profiles.some((profile) => profile.id === draft.profile_id)) {
    profileOptions.push({
      value: draft.profile_id,
      label: data ? t('environment.image_retired', { id: draft.profile_id }) : draft.profile_id,
    });
  }
  const limits = data?.workspace_gib;
  const { disk, published } = diskSummary(environments, Number(draft.workspace_gib) || 0);
  const leadHours = data?.auto_publish_lead_hours;
  // A refused archive date opens the fold, so the error shows under its field
  const showMore = moreOpen || Boolean(errors.archive_until);

  return (
    <section
      className="flex flex-col gap-4 border-t border-white/5 pt-6 mt-2"
      data-testid="workspace-settings"
    >
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-x-3">
          <h3 className="text-sm font-bold text-white">{t('environment.setting.title')}</h3>
          <Button
            variant="link"
            className="!px-0 !py-1"
            onClick={() => openGuide('admin', GUIDE_SECTION)}
          >
            {t('environment.setting.learn_more')}
          </Button>
        </div>
        <p className="text-xs text-slate-400">{t('environment.setting.hint_stages')}</p>
      </div>
      {locked && <Notice tone="warning">{t('environment.setting.locked')}</Notice>}
      <ToggleField
        id={`${fieldId}-enabled`}
        label={t('environment.setting.enabled')}
        checked={draft.enabled}
        onChange={(e) => set('enabled', e.target.checked)}
        disabled={locked}
      />
      {errors.enabled && <Notice tone="error">{errors.enabled}</Notice>}
      {draft.enabled && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <WorkspaceImagePicker
              images={data?.images}
              loadFailed={catalog.isError}
              onRetry={catalog.refetch}
              value={draft.image_id}
              onChange={(value) => set('image_id', value)}
              disabled={locked}
              error={errors.image_id}
            />
            <SelectField
              label={t('environment.setting.profile')}
              value={draft.profile_id}
              onChange={(value) => set('profile_id', value)}
              options={profileOptions}
              placeholder={
                data ? t('environment.setting.profile_placeholder') : t('common.loading')
              }
              hint={t('environment.setting.profile_hint')}
              error={errors.profile_id || false}
              disabled={locked}
              required
            />
          </div>
          <div className="flex flex-col gap-1">
            <InputField
              label={t('environment.setting.workspace_gib')}
              type="number"
              value={String(draft.workspace_gib)}
              onChange={(e) => set('workspace_gib', e.target.value)}
              min={limits?.min}
              max={limits?.max}
              hint={
                limits && !locked
                  ? t('environment.setting.workspace_gib_hint', {
                      min: limits.min,
                      max: limits.max,
                      disk,
                    })
                  : ''
              }
              error={errors.workspace_gib}
              disabled={locked}
              required
            />
            {!locked &&
              published.map((env) => (
                <p key={env.stage_id || 'competition'} className="text-[10px] text-slate-400">
                  {t('environment.setting.disk_line_locked', {
                    stage: env.stage_title || t('environment.view.competition'),
                    disk: env.disk_gib,
                  })}
                </p>
              ))}
          </div>
          <ToggleField
            id={`${fieldId}-auto`}
            label={t('environment.auto_publish')}
            checked={draft.auto_publish}
            onChange={(e) => set('auto_publish', e.target.checked)}
            disabled={locked}
            hint={
              draft.auto_publish && leadHours != null
                ? t('environment.auto_publish_status', { hours: leadHours })
                : ''
            }
          />
          <Disclosure
            label={t('environment.more_options')}
            open={showMore}
            onToggle={() => setMoreOpen(!showMore)}
          >
            <InputField
              label={t('environment.archive_until')}
              type="datetime-local"
              value={draft.archive_until}
              onChange={(e) => set('archive_until', e.target.value)}
              hint={t('environment.setting.archive_until_hint', { timezone })}
              error={errors.archive_until}
              disabled={locked}
            />
          </Disclosure>
        </>
      )}
    </section>
  );
}
