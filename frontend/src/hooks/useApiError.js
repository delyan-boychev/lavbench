import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';
import { formatLocalizedDate } from '../utils/formatDate';

// Response fields an `api.ERR_*` translation may interpolate (for example {{limit}} = "50 MB")
const INTERPOLATED_FIELDS = [
  'limit',
  'min',
  'max',
  'allowed',
  'stages',
  'file',
  'folder',
  'detail',
  'rows',
  'ids',
  'column',
  'columns',
  'count',
  'expected_ids',
  'missing_ids',
  'unexpected_ids',
];

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
      // A time from the server reads in the viewer's language and time zone
      if (body.available_at) options.available_at = formatLocalizedDate(body.available_at);
      // A machine reason has its own text, filled from the same fields; detail is English
      if (body.reason) {
        options.reason = t(`api_reasons.${body.reason}`, {
          ...options,
          defaultValue: body.detail ?? '',
        });
      } else if (body.detail != null) {
        options.reason = body.detail;
      }
      return t(`api.${data.code}`, options);
    },
    [t],
  );
}

/** Translate a task's problem code with the message fields the server stored for it. */
export function useTaskProblemText() {
  const formatApiError = useApiErrorText();
  return useCallback(
    (task, code) => formatApiError({ ...task?.problem_fields?.[code], code, error: code }),
    [formatApiError],
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
