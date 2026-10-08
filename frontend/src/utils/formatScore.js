/**
 * Format a metric score for display.
 *
 * Normal magnitudes keep four decimals; tiny non-zero values switch to four
 * significant digits so they do not collapse to "0.0000". Missing or
 * non-numeric values render as an em dash.
 *
 * @param {number | string | null | undefined} value
 * @returns {string}
 */
export function formatScore(value) {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return '—';
  if (num !== 0 && Math.abs(num) < 1e-3) return num.toPrecision(4);
  return num.toFixed(4);
}

export default formatScore;
