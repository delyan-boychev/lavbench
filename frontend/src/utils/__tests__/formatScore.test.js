import { describe, it, expect } from 'vitest';
import { formatScore } from '../formatScore';

describe('formatScore', () => {
  it('keeps four decimals for regular values', () => {
    expect(formatScore(0.123456)).toBe('0.1235');
    expect(formatScore(1)).toBe('1.0000');
    expect(formatScore(-2.5)).toBe('-2.5000');
    expect(formatScore(0.001)).toBe('0.0010');
  });

  it('renders zero with four decimals', () => {
    expect(formatScore(0)).toBe('0.0000');
  });

  it('uses significant digits for tiny non-zero values', () => {
    expect(formatScore(0.000123456)).toBe('0.0001235');
    expect(formatScore(-0.0000012345)).toBe('-0.000001234');
    expect(formatScore(1.5e-9)).toBe('1.500e-9');
  });

  it('accepts numeric strings', () => {
    expect(formatScore('0.5')).toBe('0.5000');
  });

  it('returns an em dash for missing or invalid values', () => {
    expect(formatScore(null)).toBe('—');
    expect(formatScore(undefined)).toBe('—');
    expect(formatScore(NaN)).toBe('—');
    expect(formatScore('')).toBe('—');
    expect(formatScore('abc')).toBe('—');
    expect(formatScore(Infinity)).toBe('—');
  });
});
