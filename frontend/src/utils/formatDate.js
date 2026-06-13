import i18n from '../i18n';

/**
 * Formats a date string/object according to the active UI language.
 * @param {string|Date} dateVal 
 * @param {object} options Optional overrides for Intl.DateTimeFormat
 * @returns {string}
 */
export function formatLocalizedDate(dateVal, options = {}) {
  if (!dateVal) return '';
  const date = new Date(dateVal);
  if (isNaN(date.getTime())) return '';

  // Use the active i18n language or fallback to 'en'
  const currentLanguage = i18n.language || 'en';

  const defaultOptions = {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    ...options
  };

  return new Intl.DateTimeFormat(currentLanguage, defaultOptions).format(date);
}
