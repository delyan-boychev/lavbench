import React, { useEffect, useId } from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import Notice from '../ui/Notice';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import WorkspaceImagePicker from './WorkspaceImagePicker';
import { workspacesOffered } from '../../hooks/useEnvironmentQuery';
import { withCatalogDefaults } from '../../utils/workspaceSetting';

function diskLine(t, env, workspaceGib) {
  if (env.published_at) {
    return t('environment.setting.disk_line_locked', {
      stage: env.stage_title,
      disk: env.disk_gib,
    });
  }
  const values = {
    stage: env.stage_title,
    workspace: workspaceGib,
    data: env.data_gib,
    disk: workspaceGib + env.data_gib,
  };
  return env.stage_title
    ? t('environment.setting.disk_line_stage', values)
    : t('environment.setting.disk_line', values);
}

/**
 * The "Student workspaces" section of the competition create and edit forms, saved with them.
 * @param {{
 *   draft: import('../../utils/workspaceSetting').WorkspaceDraft,
 *   onChange: (draft: import('../../utils/workspaceSetting').WorkspaceDraft) => void,
 *   catalog: { data?: any, isError: boolean, error: unknown },
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
  const fieldId = useId();
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
  const workspaceGib = Number(draft.workspace_gib) || 0;
  const diskRows = environments.length ? environments : [{ stage_title: null, data_gib: 0 }];

  return (
    <section
      className="flex flex-col gap-4 border-t border-white/5 pt-6 mt-2"
      data-testid="workspace-settings"
    >
      <h3 className="text-sm font-bold text-white">{t('environment.setting.title')}</h3>
      <ToggleField
        id={`${fieldId}-enabled`}
        label={t('environment.setting.enabled')}
        checked={draft.enabled}
        onChange={(e) => set('enabled', e.target.checked)}
      />
      {errors.enabled && <Notice tone="error">{errors.enabled}</Notice>}
      {draft.enabled && (
        <>
          <Notice>{t('environment.setting.hint_stages')}</Notice>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <WorkspaceImagePicker
              images={data?.images}
              loadFailed={catalog.isError}
              value={draft.image_id}
              onChange={(value) => set('image_id', value)}
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
              required
            />
          </div>
          <InputField
            label={t('environment.setting.workspace_gib')}
            type="number"
            value={String(draft.workspace_gib)}
            onChange={(e) => set('workspace_gib', e.target.value)}
            min={limits?.min}
            max={limits?.max}
            hint={
              limits
                ? t('environment.setting.workspace_gib_hint', { min: limits.min, max: limits.max })
                : ''
            }
            error={errors.workspace_gib}
            required
          />
          <Notice>
            <p className="font-semibold">{t('environment.setting.disk_title')}</p>
            <ul className="mt-1">
              {diskRows.map((env) => (
                <li key={env.stage_id || env.id || 'competition'}>
                  {diskLine(t, env, workspaceGib)}
                </li>
              ))}
            </ul>
            <p className="mt-1">{t('environment.setting.disk_hint')}</p>
          </Notice>
          <ToggleField
            id={`${fieldId}-auto`}
            label={t('environment.auto_publish')}
            checked={draft.auto_publish}
            onChange={(e) => set('auto_publish', e.target.checked)}
          />
          <Notice>{t('environment.setting.schedule_hint')}</Notice>
          <InputField
            label={t('environment.archive_until')}
            type="datetime-local"
            value={draft.archive_until}
            onChange={(e) => set('archive_until', e.target.value)}
            hint={t('environment.setting.archive_until_hint', { timezone })}
            error={errors.archive_until}
          />
        </>
      )}
    </section>
  );
}
