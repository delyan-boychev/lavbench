// Spread retries and refetches over a window so clients that saw the same event or the
// same outage do not hit the server at the same instant
export const JITTER_RATIO = 0.3;

/**
 * Return `ms` scaled by a random factor in [1 - ratio, 1 + ratio].
 * @param {number} ms
 * @param {number} [ratio]
 * @returns {number}
 */
export function withJitter(ms, ratio = JITTER_RATIO) {
  return Math.round(ms * (1 - ratio + Math.random() * 2 * ratio));
}
