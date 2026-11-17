import { useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';

// Editors with unsaved changes; one place, so the admin sidebar can ask before leaving them
const dirtyEditors = new Set();

/** Register unsaved changes, which also makes the browser ask before the page unloads. */
export function useUnsavedChanges(dirty) {
  useEffect(() => {
    if (!dirty) return undefined;
    const token = {};
    dirtyEditors.add(token);
    const onBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      dirtyEditors.delete(token);
      window.removeEventListener('beforeunload', onBeforeUnload);
    };
  }, [dirty]);
}

/** Whether any open editor has unsaved changes. */
export function hasUnsavedChanges() {
  return dirtyEditors.size > 0;
}

/**
 * Ask before discarding unsaved changes; resolves true when it is fine to leave.
 * @returns {(dirty?: boolean) => Promise<boolean>}
 */
export function useDiscardGuard() {
  const { t } = useTranslation();
  const { confirm } = useNotifications();
  return useCallback(
    async (dirty = hasUnsavedChanges()) => {
      if (!dirty) return true;
      const ok = await confirm({
        title: t('common.unsaved.title'),
        message: t('common.unsaved.message'),
        confirmText: t('common.unsaved.discard'),
        cancelText: t('common.unsaved.keep_editing'),
      });
      return Boolean(ok);
    },
    [confirm, t],
  );
}
