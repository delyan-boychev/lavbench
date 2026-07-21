import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';

export function useApiError() {
  const { showToast } = useNotifications();
  const { t } = useTranslation();

  const showApiError = useCallback(
    (data, fallbackKey, defaultText = '') => {
      if (data?.code) {
        showToast(t(`api.${data.code}`, data.error || t(fallbackKey, defaultText)), 'rose');
      } else {
        showToast(data?.error || t(fallbackKey, defaultText), 'rose');
      }
    },
    [showToast, t],
  );

  return { showApiError };
}
