import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import { TIMEZONES } from '../../utils/timezones';

/** Local datetime value of an API time, or of a value the form already holds. */
const asLocal = (value) => (value ? String(value).substring(0, 16) : '');

/**
 * The fields of a competition, shared by the create and edit forms.
 * @param {{
 *   value: Record<string, any>,
 *   onChange: (patch: Record<string, any>) => void,
 *   idPrefix: string,
 *   testStage?: { start_time?: string, end_time?: string } | null,
 *   errors?: Record<string, string>,
 *   onFieldEdit?: (name: string) => void,
 * }} props
 */
export default function CompetitionFields({
  value,
  onChange,
  idPrefix,
  testStage = null,
  errors = {},
  onFieldEdit = undefined,
}) {
  const { t } = useTranslation();
  const number = (key) => (e) => onChange({ [key]: parseInt(e.target.value) || 0 });
  // The edit form shows the existing test stage until its times are changed
  const testTime = (key, stageKey) =>
    value[key] !== undefined ? value[key] || '' : asLocal(testStage?.[stageKey]);

  return (
    <>
      <InputField
        label={t('admin.competition_title')}
        value={value.title}
        onChange={(e) => onChange({ title: e.target.value })}
        required
      />
      <InputField
        multiline
        label={t('admin.description')}
        value={value.description ?? ''}
        onChange={(e) => onChange({ description: e.target.value })}
        rows={4}
      />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <InputField
          label={t('admin.daily_limits')}
          type="number"
          value={value.max_eval_requests}
          onChange={number('max_eval_requests')}
        />
        <InputField
          label={t('admin.ram_limit_override')}
          type="number"
          value={value.ram_limit_mb ?? ''}
          onChange={number('ram_limit_mb')}
        />
        <InputField
          label={t('admin.time_limit_override')}
          type="number"
          value={value.time_limit_sec ?? ''}
          onChange={number('time_limit_sec')}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <InputField
          label={t('admin.stages.start_time_label')}
          type="datetime-local"
          value={asLocal(value.start_time)}
          onChange={(e) => onChange({ start_time: e.target.value })}
          required
        />
        <InputField
          label={t('admin.stages.end_time_label')}
          type="datetime-local"
          value={asLocal(value.end_time)}
          onChange={(e) => onChange({ end_time: e.target.value })}
          required
        />
        <SelectField
          label={t('admin.timezone_choose')}
          value={value.timezone || 'UTC'}
          onChange={(val) => onChange({ timezone: val })}
          options={TIMEZONES}
          required
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
        <InputField
          label={t('admin.test_stage_start')}
          type="datetime-local"
          value={testTime('test_stage_start_time', 'start_time')}
          onChange={(e) => onChange({ test_stage_start_time: e.target.value })}
        />
        <InputField
          label={t('admin.test_stage_end')}
          type="datetime-local"
          value={testTime('test_stage_end_time', 'end_time')}
          onChange={(e) => {
            onFieldEdit?.('test_stage_end_time');
            onChange({ test_stage_end_time: e.target.value });
          }}
          error={errors.test_stage_end_time}
        />
      </div>
      <div className="flex flex-col gap-3 mt-2.5">
        <ToggleField
          label={t('admin.requires_gpu_workers')}
          id={`${idPrefix}-gpu-req`}
          checked={value.gpu_required}
          onChange={(e) => onChange({ gpu_required: e.target.checked })}
        />
        <ToggleField
          label={t('admin.double_blind_eval')}
          id={`${idPrefix}-double-blind`}
          checked={value.double_blind !== false}
          onChange={(e) => onChange({ double_blind: e.target.checked })}
        />
        <ToggleField
          label={t('admin.freeze_label')}
          id={`${idPrefix}-is-frozen`}
          checked={value.is_frozen || false}
          onChange={(e) => onChange({ is_frozen: e.target.checked })}
        />
      </div>
    </>
  );
}
