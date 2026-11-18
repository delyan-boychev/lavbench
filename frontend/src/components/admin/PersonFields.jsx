import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';

/**
 * A person's name and, for competitors, birth date, school details, competition and the
 * anonymity choice. Shared by the register and edit forms for competitors and accounts.
 * @param {{
 *   value: Record<string, any>,
 *   onChange: (patch: Record<string, any>) => void,
 *   idPrefix: string,
 *   competitor?: boolean,
 *   challenges?: Array<{ id: number | string, title: string }>,
 *   errors?: Record<string, string>,
 * }} props
 */
export default function PersonFields({
  value,
  onChange,
  idPrefix,
  competitor = true,
  challenges = [],
  errors = {},
}) {
  const { t } = useTranslation();
  const text = (key, label, extra = {}) => (
    <InputField
      label={label}
      value={value[key] ?? ''}
      onChange={(e) => onChange({ [key]: e.target.value })}
      error={errors[key]}
      required
      {...extra}
    />
  );

  return (
    <>
      <div className={`grid grid-cols-1 ${competitor ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-4`}>
        {text('name', t('admin.competitor_reg.first_name'))}
        {competitor && text('middle_name', t('admin.competitor_reg.middle_name'))}
        {text('surname', t('admin.competitor_reg.last_name'))}
      </div>
      {competitor && (
        <>
          {text('birth_date', t('admin.competitor_reg.birth_date'), { type: 'date' })}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {text('grade', t('admin.competitor_reg.grade'))}
            {text('school', t('admin.competitor_reg.school'))}
            {text('city', t('admin.competitor_reg.city'))}
          </div>
          <SelectField
            label={t('admin.competitor_reg.assign_competition')}
            value={value.challenge_id}
            onChange={(val) => onChange({ challenge_id: val })}
            error={errors.challenge_id || false}
            required
            options={[
              { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
              ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
            ]}
          />
          <div className="mt-2.5">
            <ToggleField
              label={t('admin.competitor_reg.anonymous_help')}
              id={`${idPrefix}-is-anonymous`}
              checked={value.is_anonymous}
              onChange={(e) => onChange({ is_anonymous: e.target.checked })}
            />
          </div>
        </>
      )}
    </>
  );
}
