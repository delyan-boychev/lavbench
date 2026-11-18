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
  // Scoring often takes under a second, which would otherwise read as "0 sec"
  if (seconds > 0 && seconds < 1) {
    return new Intl.NumberFormat(locale, {
      style: 'unit',
      unit: 'millisecond',
      unitDisplay: 'short',
    }).format(Math.max(1, Math.round(seconds * 1000)));
  }
  const { unit, value } = pickUnit(seconds);
  return new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'short' }).format(value);
}

// Binary sizes in the units the server's limits use ("20 MB" means 20 MiB)
const SIZE_UNITS = /** @type {const} */ ([
  ['gigabyte', 1024 ** 3],
  ['megabyte', 1024 ** 2],
  ['kilobyte', 1024],
]);

/**
 * Format a file size, e.g. "1.4 MB" or "512 byte".
 * @param {number} bytes
 * @param {string} locale
 * @returns {string}
 */
export function formatBytes(bytes, locale) {
  const value = Math.max(0, Number(bytes) || 0);
  const [unit, size] = SIZE_UNITS.find(([, s]) => value >= s) ?? ['byte', 1];
  return new Intl.NumberFormat(locale, {
    style: 'unit',
    unit,
    unitDisplay: 'short',
    maximumFractionDigits: 1,
  }).format(value / size);
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
