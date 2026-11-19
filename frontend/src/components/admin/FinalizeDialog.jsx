import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import Modal from '../ui/Modal';
import ToggleField from '../ui/ToggleField';
import Notice from '../ui/Notice';
import { useApiErrorText } from '../../hooks/useApiError';
import { finalizeReasonCode } from '../../hooks/useFinalizeStatusQuery';

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
 *   readiness?: { ready: boolean, reason?: string | null, available_at?: string | null, pending_runs?: number } | null,
 *   isStage?: boolean,
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
  readiness = null,
  isStage = false,
}) {
  const { t } = useTranslation();
  const formatApiError = useApiErrorText();
  // The server decides when finalising is possible; the dialog only says why not yet
  const blocked = readiness ? !readiness.ready : false;
  const blockedText = blocked
    ? formatApiError({
        code: finalizeReasonCode(readiness.reason, isStage),
        available_at: readiness.available_at,
        count: readiness.pending_runs,
      })
    : '';
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="sm">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!isPending && !blocked) onConfirm();
        }}
        className="flex flex-col gap-6"
      >
        {blocked && (
          <Notice tone="warning" role="status">
            {blockedText}
          </Notice>
        )}
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
          <Button type="submit" isLoading={isPending} disabled={blocked}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
