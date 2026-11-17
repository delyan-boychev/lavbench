import { useCallback, useState } from 'react';
import { useApiErrorText } from './useApiError';

/**
 * Errors naming a request field (`workspace.workspace_gib`), keyed by the name after `prefix`.
 * @param {string} [prefix]
 */
export function useFieldErrors(prefix = '') {
  const formatApiError = useApiErrorText();
  const [errors, setErrors] = useState(/** @type {Record<string, string>} */ ({}));

  /** Show the error under its field; false when it names no field of this form. */
  const capture = useCallback(
    (error) => {
      const body = error?.data && typeof error.data === 'object' ? error.data : error;
      const field = typeof body?.field === 'string' ? body.field : '';
      if (!field.startsWith(prefix) || field === prefix) return false;
      setErrors({ [field.slice(prefix.length)]: formatApiError(error) });
      return true;
    },
    [prefix, formatApiError],
  );

  const clear = useCallback((name) => {
    setErrors((prev) => {
      if (!(name in prev)) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }, []);

  const reset = useCallback(() => setErrors({}), []);

  return { errors, capture, clear, reset };
}
