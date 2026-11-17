import React from 'react';
import { useTranslation } from 'react-i18next';
import Notice from '../ui/Notice';

/**
 * Why a jury member cannot register or change competitors: the competition has started.
 * @param {{ bulk?: boolean }} props
 */
export default function CompetitionStartedNotice({ bulk = false }) {
  const { t } = useTranslation();
  return (
    <Notice tone="error" role="alert" className="font-semibold">
      {bulk
        ? t('admin.competitor_reg.bulk_import_started_warning')
        : t('admin.competitor_reg.competition_started_warning')}
    </Notice>
  );
}
