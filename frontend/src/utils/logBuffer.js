export const MAX_LOG_CHARS = 500_000;

/**
 * Append a chunk to a log string, keeping only the most recent `maxChars` characters.
 * Trimming happens at a line boundary so the first visible line is never cut in half.
 * @param {string} prev
 * @param {string} chunk
 * @param {number} [maxChars]
 * @returns {string}
 */
export function appendCappedLog(prev, chunk, maxChars = MAX_LOG_CHARS) {
  const combined = prev + chunk;
  if (combined.length <= maxChars) return combined;
  const tail = combined.slice(combined.length - maxChars);
  const firstNewline = tail.indexOf('\n');
  return firstNewline >= 0 && firstNewline < tail.length - 1 ? tail.slice(firstNewline + 1) : tail;
}
