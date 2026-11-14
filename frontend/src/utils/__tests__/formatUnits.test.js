import { describe, it, expect } from 'vitest';
import { formatDuration, formatGigabytes, formatTimeAgo } from '../formatUnits';

describe('formatDuration', () => {
  it.each([
    [0, '0 sec'],
    [45, '45 sec'],
    [125, '2 min'],
    [7200, '2 hr'],
    [90_000, '1 day'],
  ])('formats %s seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds, 'en')).toBe(expected);
  });

  it('follows the locale', () => {
    expect(formatDuration(125, 'bg')).toBe('2 мин');
  });
});

describe('formatTimeAgo', () => {
  it.each([
    [0, 'now'],
    [12, '12 seconds ago'],
    [180, '3 minutes ago'],
    [-5, 'now'],
  ])('formats %s seconds as %s', (seconds, expected) => {
    expect(formatTimeAgo(seconds, 'en')).toBe(expected);
  });

  it('follows the locale', () => {
    expect(formatTimeAgo(12, 'bg')).toBe('преди 12 секунди');
  });
});

describe('formatGigabytes', () => {
  it('rounds to one decimal place', () => {
    expect(formatGigabytes(15.64, 'en')).toBe('15.6 GB');
    expect(formatGigabytes(64, 'en')).toBe('64 GB');
  });
});
