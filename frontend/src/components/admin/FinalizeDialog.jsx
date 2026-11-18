import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import ToggleField from '../ui/ToggleField';

/**
 * The jury's finalize confirmation for a stage or a competition, with the choice to reveal
 * the results at the same time.
 * @param {{
 *   isOpen: boolean,
 *   title: string,
 *   revealLabel: string,
 *   revealId: string,
 *   reveal: boolean,
 *   onRevealChange: (reveal: boolean) => void,
 *   confirmLabel: string,
 *   isPending: boolean,
 *   onConfirm: () => void,
 *   onClose: () => void,
 * }} props
 */
export default function FinalizeDialog({
  isOpen,
  title,
  revealLabel,
  revealId,
  reveal,
  onRevealChange,
  confirmLabel,
  isPending,
  onConfirm,
  onClose,
}) {
  const { t } = useTranslation();
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="sm">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!isPending) onConfirm();
        }}
        className="flex flex-col gap-6"
      >
        <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
          <ToggleField
            label={revealLabel}
            id={revealId}
            checked={reveal}
            onChange={(e) => onRevealChange(e.target.checked)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" isLoading={isPending}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
