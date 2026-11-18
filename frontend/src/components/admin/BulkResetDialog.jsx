import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import SelectField from '../ui/SelectField';

/**
 * Pick the competition whose competitors all get new passwords; the caller confirms next.
 * Mounted only while open, so each opening starts with no competition chosen.
 * @param {{
 *   challenges: Array<{ id: number | string, title: string }>,
 *   onClose: () => void,
 *   onChoose: (challenge: { id: number | string, title: string }) => void,
 * }} props
 */
export default function BulkResetDialog({ challenges, onClose, onChoose }) {
  const { t } = useTranslation();
  const [challengeId, setChallengeId] = useState('');

  const submit = (e) => {
    e.preventDefault();
    const challenge = challenges.find((c) => c.id.toString() === challengeId);
    if (challenge) onChoose(challenge);
  };

  return (
    <Modal isOpen onClose={onClose} title={t('admin.confirm.bulk_reset_title')} size="sm">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <p className="text-sm text-slate-300 leading-relaxed">
          {t('admin.confirm.bulk_reset_choose')}
        </p>
        <SelectField
          label={t('admin.confirm.bulk_reset_competition')}
          value={challengeId}
          onChange={setChallengeId}
          required
          options={challenges.map((c) => ({ value: c.id.toString(), label: c.title }))}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit">{t('common.continue')}</Button>
        </div>
      </form>
    </Modal>
  );
}
