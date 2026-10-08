import { describe, it, expect } from 'vitest';
import { appendCappedLog, MAX_LOG_CHARS } from '../logBuffer';

describe('appendCappedLog', () => {
  it('appends when under the cap', () => {
    expect(appendCappedLog('a\n', 'b\n', 100)).toBe('a\nb\n');
  });

  it('keeps only the newest characters, trimmed at a line boundary', () => {
    const result = appendCappedLog('line-one\nline-two\n', 'line-three\n', 20);
    expect(result.length).toBeLessThanOrEqual(20);
    expect(result).toBe('line-three\n');
  });

  it('falls back to a hard cut when there is no newline in the kept tail', () => {
    const result = appendCappedLog('', 'x'.repeat(50), 10);
    expect(result).toBe('x'.repeat(10));
  });

  it('defaults to a roughly 500KB cap', () => {
    const big = 'y'.repeat(99) + '\n';
    let log = '';
    for (let i = 0; i < 6000; i++) log = appendCappedLog(log, big);
    expect(MAX_LOG_CHARS).toBe(500_000);
    expect(log.length).toBeLessThanOrEqual(MAX_LOG_CHARS);
    expect(log.startsWith('y')).toBe(true);
  });
});
