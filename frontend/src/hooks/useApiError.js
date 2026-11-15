import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';

// Response fields an `api.ERR_*` translation may interpolate (for example {{limit}} = "50 MB")
const INTERPOLATED_FIELDS = ['limit'];

export function useApiError() {
  const { showToast } = useNotifications();
  const { t } = useTranslation();

  const showApiError = useCallback(
    (data, fallbackKey, defaultText = '') => {
      if (data?.code) {
        // An ApiRequestError keeps the response body in .data
        const body = data.data && typeof data.data === 'object' ? data.data : data;
        const options = { defaultValue: data.error || t(fallbackKey, defaultText) };
        for (const field of INTERPOLATED_FIELDS) {
          if (body[field] != null) options[field] = body[field];
        }
        showToast(t(`api.${data.code}`, options), 'rose');
      } else {
        showToast(data?.error || t(fallbackKey, defaultText), 'rose');
      }
    },
    [showToast, t],
  );

  return { showApiError };
}
