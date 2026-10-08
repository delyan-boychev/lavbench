/** Manual points are 0-100 with at most 2 decimal places, mirroring backend validation. */

const POINTS_PATTERN = /^\d{1,3}([.,]\d{1,2})?$/;

/**
 * Parse user input into points, or null when it is not a valid 0-100 value
 * with at most 2 decimals. Accepts a decimal comma for Bulgarian keyboards.
 *
 * @param {string | number} input
 * @returns {number | null}
 */
export function parsePoints(input) {
  const text = String(input).trim();
  if (!POINTS_PATTERN.test(text)) return null;
  const value = Number(text.replace(',', '.'));
  return value >= 0 && value <= 100 ? value : null;
}

/**
 * Round to 2 decimals so summed points never show float noise like 0.30000000000000004.
 *
 * @param {number | null | undefined} value
 * @returns {number}
 */
export function roundPoints(value) {
  const num = Number(value);
  return Number.isFinite(num) ? Math.round(num * 100) / 100 : 0;
}
