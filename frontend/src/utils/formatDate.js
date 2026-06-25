import i18n from '../i18n';

/**
 * Formats a date string/object according to the active UI language.
 * Always includes the year for unambiguous display.
 *
 * @param {string|Date|number} dateVal
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
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...options,
  };

  return new Intl.DateTimeFormat(currentLanguage, defaultOptions).format(date);
}

/**
 * Formats a date/time string for display with timezone label.
 * Locale-aware (uses the active i18n language).
 * Output example: "25 Jun 2026, 18:30 (Europe Sofia)"
 *
 * @param {string|Date|number} dateStr
 * @param {string} [tz] IANA timezone string (e.g. 'Europe/Sofia'). Defaults to 'UTC'.
 * @returns {string}
 */
export function formatDateTime(dateStr, tz) {
  if (!dateStr) return '—';
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '—';

    const targetTz = tz || 'UTC';
    const currentLanguage = i18n.language || 'en';
    const tzLabel = targetTz.replace(/_/g, ' ');

    const formatted = new Intl.DateTimeFormat(currentLanguage, {
      timeZone: targetTz,
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);

    return `${formatted} (${tzLabel})`;
  } catch {
    // Fallback: UTC manual formatting
    const d = new Date(dateStr);
    const pad = (n) => n.toString().padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} (UTC)`;
  }
}
