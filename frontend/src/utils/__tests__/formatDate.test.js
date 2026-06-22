import { describe, it, expect, vi, beforeEach } from 'vitest';
import { formatLocalizedDate } from '../formatDate';

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

  it('respects custom Intl.DateTimeFormat options', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date, { year: 'numeric', month: 'long', day: 'numeric' });
    expect(result).toContain('2024');
    expect(result).toContain('March');
  });

  it('uses i18n language for locale', () => {
    const date = new Date('2024-03-15T10:30:00');
    const result = formatLocalizedDate(date);
    // en locale: "Mar 15, 10:30 AM" format
    expect(result).toMatch(/Mar/);
  });
});
