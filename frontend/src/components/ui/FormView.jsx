import React, { useEffect, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft } from 'lucide-react';
import Button from './Button';
import { useEditorFocus } from '../../hooks/useEditorFocus';
import { useDiscardGuard, useUnsavedChanges } from '../../hooks/useUnsavedChanges';
import { focusField } from '../../utils/reveal';

/**
 * The one frame for every create or edit form (see AGENTS.md, Frontend components).
 *
 * @param {{
 *   title: React.ReactNode,
 *   description?: React.ReactNode,
 *   onSubmit: (event: React.FormEvent<HTMLFormElement>) => void,
 *   onCancel?: (() => void) | null,
 *   showBack?: boolean,
 *   dirty?: boolean,
 *   errors?: Record<string, string> | null,
 *   submitLabel: React.ReactNode,
 *   submitVariant?: string,
 *   submitting?: boolean,
 *   submitDisabled?: boolean,
 *   autoFocus?: boolean,
 *   className?: string,
 *   testId?: string,
 *   children: React.ReactNode,
 * }} props
 */
export default function FormView({
  title,
  description = null,
  onSubmit,
  onCancel = null,
  showBack = true,
  dirty = false,
  errors = null,
  submitLabel,
  submitVariant = 'primary',
  submitting = false,
  submitDisabled = false,
  autoFocus = true,
  className = '',
  testId = undefined,
  children,
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const rootRef = useRef(null);
  const formRef = useRef(null);
  // Set by a submit, cleared once the errors it produced have been focused
  const awaitingErrors = useRef(false);
  const confirmDiscard = useDiscardGuard();

  useEditorFocus(rootRef, { focus: autoFocus ? 'field' : null });
  useUnsavedChanges(dirty);

  // The fields cancel the browser's own invalid bubble, so focus the first one here
  useEffect(() => {
    const form = formRef.current;
    if (!form) return undefined;
    let first = null;
    const onInvalid = (event) => {
      if (first) return;
      first = event.target;
      setTimeout(() => {
        focusField(first);
        first = null;
      }, 0);
    };
    form.addEventListener('invalid', onInvalid, true);
    return () => form.removeEventListener('invalid', onInvalid, true);
  }, []);

  useEffect(() => {
    if (!awaitingErrors.current || !errors || Object.keys(errors).length === 0) return;
    awaitingErrors.current = false;
    focusField(formRef.current?.querySelector('[aria-invalid="true"]'));
  }, [errors]);

  const handleSubmit = (event) => {
    event.preventDefault();
    awaitingErrors.current = true;
    onSubmit(event);
  };

  const handleCancel = async () => {
    if (await confirmDiscard(dirty)) onCancel?.();
  };

  return (
    <section
      ref={rootRef}
      aria-labelledby={titleId}
      data-testid={testId}
      className={`admin-card px-5 pt-5 md:px-8 md:pt-8 animate-fadein ${className}`}
    >
      <div className="flex flex-wrap justify-between items-start gap-3 mb-6 border-b border-white/5 pb-4">
        <div className="min-w-0">
          <h2 id={titleId} tabIndex={-1} className="text-xl font-bold text-white">
            {title}
          </h2>
          {description && <p className="text-slate-400 text-xs mt-1">{description}</p>}
        </div>
        {showBack && onCancel && (
          <Button variant="secondary" onClick={handleCancel}>
            <ArrowLeft size={14} aria-hidden="true" />
            {t('common.back')}
          </Button>
        )}
      </div>
      <form ref={formRef} onSubmit={handleSubmit} className="flex flex-col gap-4">
        {children}
        <div className="sticky bottom-0 z-10 -mx-5 md:-mx-8 px-5 md:px-8 py-4 mt-2 flex flex-wrap justify-end gap-3 bg-[#0d0e18] border-t border-white/5 rounded-b-2xl">
          {onCancel && (
            <Button variant="secondary" onClick={handleCancel}>
              {t('common.cancel')}
            </Button>
          )}
          <Button
            type="submit"
            variant={submitVariant}
            disabled={submitDisabled || submitting}
            isLoading={submitting}
          >
            {submitLabel}
          </Button>
        </div>
      </form>
    </section>
  );
}
