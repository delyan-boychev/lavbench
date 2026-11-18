import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import InputField from '../ui/InputField';
import Modal from '../ui/Modal';
import { toDateTimeLocal } from '../../utils/formatDate';

/**
 * Extension dialog, mounted only while open so each opening starts from the current end.
 * @param {{
 *   currentEnd: string,
 *   timezone: string,
 *   isPending: boolean,
 *   errors?: Record<string, string>,
 *   onFieldEdit?: (field: string) => void,
 *   onClose: () => void,
 *   onSubmit: (body: { end_time: string, reason: string }) => void,
 * }} props
 */
export default function ExtendEnvironmentModal({
  currentEnd,
  timezone,
  isPending,
  errors = /** @type {Record<string, string>} */ ({}),
  onFieldEdit = undefined,
  onClose,
  onSubmit,
}) {
  const { t } = useTranslation();
  const [endTime, setEndTime] = useState(() => toDateTimeLocal(currentEnd));
  const [reason, setReason] = useState('');

  const submit = (e) => {
    e.preventDefault();
    if (isPending) return;
    onSubmit({ end_time: endTime, reason: reason.trim() });
  };

  return (
    <Modal isOpen onClose={onClose} title={t('environment.extend_title')} size="sm">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <InputField
          label={t('environment.extend_end')}
          type="datetime-local"
          value={endTime}
          onChange={(e) => {
            onFieldEdit?.('end_time');
            setEndTime(e.target.value);
          }}
          hint={t('environment.extend_end_hint', { timezone })}
          error={errors.end_time}
          required
        />
        <InputField
          multiline
          rows={3}
          label={t('environment.extend_reason')}
          value={reason}
          onChange={(e) => {
            onFieldEdit?.('reason');
            setReason(e.target.value);
          }}
          hint={t('environment.extend_reason_hint')}
          error={errors.reason}
          required
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" isLoading={isPending}>
            {t('environment.extend_submit')}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
