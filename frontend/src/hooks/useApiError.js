import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';

// Response fields an `api.ERR_*` translation may interpolate (for example {{limit}} = "50 MB")
const INTERPOLATED_FIELDS = ['limit'];

/** Translate an API error body the way every toast does, with its extra fields filled in. */
export function useApiErrorText() {
  const { t } = useTranslation();
  return useCallback(
    (data, fallbackKey = '', defaultText = '') => {
      if (!data?.code) return data?.error || t(fallbackKey, defaultText);
      // An ApiRequestError keeps the response body in .data
      const body = data.data && typeof data.data === 'object' ? data.data : data;
      const options = { defaultValue: data.error || t(fallbackKey, defaultText) };
      for (const field of INTERPOLATED_FIELDS) {
        if (body[field] != null) options[field] = body[field];
      }
      return t(`api.${data.code}`, options);
    },
    [t],
  );
}

export function useApiError() {
  const { showToast } = useNotifications();
  const formatApiError = useApiErrorText();

  const showApiError = useCallback(
    (data, fallbackKey, defaultText = '') => {
      showToast(formatApiError(data, fallbackKey, defaultText), 'rose');
    },
    [showToast, formatApiError],
  );

  return { showApiError };
}
