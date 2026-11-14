// Largest unit first; a duration is shown in the largest unit it reaches
const TIME_UNITS = /** @type {const} */ ([
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
  ['second', 1],
]);

function pickUnit(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  const [unit, size] = TIME_UNITS.find(([, s]) => whole >= s) ?? TIME_UNITS[3];
  return { unit, value: Math.floor(whole / size) };
}

/**
 * Format a duration such as a queue wait, e.g. "45 sec" or "2 min".
 * @param {number} seconds
 * @param {string} locale
 * @returns {string}
 */
export function formatDuration(seconds, locale) {
  const { unit, value } = pickUnit(seconds);
  return new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'short' }).format(value);
}

/**
 * Format how long ago something happened, e.g. "12 seconds ago" or "now".
 * @param {number} seconds
 * @param {string} locale
 * @returns {string}
 */
export function formatTimeAgo(seconds, locale) {
  const { unit, value } = pickUnit(seconds);
  return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(-value, unit);
}

/**
 * Format a size given in gigabytes, e.g. "15.6 GB".
 * @param {number} gigabytes
 * @param {string} locale
 * @returns {string}
 */
export function formatGigabytes(gigabytes, locale) {
  return new Intl.NumberFormat(locale, {
    style: 'unit',
    unit: 'gigabyte',
    maximumFractionDigits: 1,
  }).format(gigabytes);
}
