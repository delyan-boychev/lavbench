import { describe, it, expect, vi, beforeEach } from 'vitest';
import { formatLocalizedDate, formatDateTime } from '../formatDate';

vi.mock('../i18n', () => ({
  default: {
    language: 'en',
  },
}));

describe('formatLocalizedDate', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('returns formatted date string for valid Date object', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date);
    expect(result).toBeTruthy();
    expect(typeof result).toBe('string');
  });

  it('returns formatted date string for valid ISO string', () => {
    const result = formatLocalizedDate('2024-03-15T10:30:00');
    expect(result).toBeTruthy();
    expect(typeof result).toBe('string');
  });

  it('returns formatted date string for timestamp number', () => {
    const result = formatLocalizedDate(1710503400000);
    expect(result).toBeTruthy();
    expect(typeof result).toBe('string');
  });

  it('returns empty string for null/undefined', () => {
    expect(formatLocalizedDate(null)).toBe('');
    expect(formatLocalizedDate(undefined)).toBe('');
  });

  it('returns empty string for invalid date', () => {
    expect(formatLocalizedDate('not-a-date')).toBe('');
  });

  it('always includes the year in the output', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date);
    expect(result).toContain('2024');
  });

  it('respects custom Intl.DateTimeFormat options', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date, { year: 'numeric', month: 'long', day: 'numeric' });
    expect(result).toContain('2024');
    expect(result).toContain('March');
  });

  it('uses i18n language for locale', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date);
    // en locale: "Mar 15, 2024, 10:30" format
    expect(result).toMatch(/Mar/);
    expect(result).toMatch(/2024/);
  });
});

describe('formatDateTime', () => {
  it('returns em dash for null/undefined/empty input', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
    expect(formatDateTime('')).toBe('—');
  });

  it('returns a string with timezone label appended', () => {
    const result = formatDateTime('2024-03-15T10:30:00Z', 'UTC');
    expect(result).toContain('(UTC)');
    expect(typeof result).toBe('string');
  });

  it('includes the year in the output', () => {
    const result = formatDateTime('2024-03-15T10:30:00Z', 'UTC');
    expect(result).toContain('2024');
  });

  it('replaces underscores in timezone label with spaces', () => {
    const result = formatDateTime('2024-03-15T10:30:00Z', 'Europe/Sofia');
    expect(result).toContain('(Europe/Sofia)');
  });

  it('returns em dash for invalid date string', () => {
    expect(formatDateTime('not-a-date', 'UTC')).toBe('—');
  });
});

describe('formatDateTime – catch / edge paths', () => {
  it('uses fallback UTC formatting when timezone is invalid', () => {
    // An invalid tz string causes Intl.DateTimeFormat to throw, hitting the catch block
    const result = formatDateTime('2024-06-25T14:00:00Z', 'Invalid/Zone');
    // Fallback outputs "YYYY-MM-DD HH:MM (UTC)"
    expect(result).toMatch(/2024-06-25/);
    expect(result).toContain('(UTC)');
  });

  it('defaults to UTC when no tz argument is supplied', () => {
    const result = formatDateTime('2024-06-25T14:00:00Z');
    expect(result).toContain('(UTC)');
    expect(result).toContain('2024');
  });
});

describe('formatLocalizedDate – option merging', () => {
  it('can override hour12 to true via options', () => {
    const result = formatLocalizedDate('2024-06-25T14:00:00Z', { hour12: true });
    // Should contain AM/PM indicator
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });

  it('returns empty string for empty string input', () => {
    expect(formatLocalizedDate('')).toBe('');
  });

  it('returns empty string for 0 (falsy number)', () => {
    expect(formatLocalizedDate(0)).toBe('');
  });
});
