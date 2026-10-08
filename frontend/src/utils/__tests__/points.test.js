import { describe, it, expect } from 'vitest';
import { parsePoints, roundPoints } from '../points';

describe('parsePoints', () => {
  it.each([
    ['0', 0],
    ['100', 100],
    ['87.5', 87.5],
    ['12.34', 12.34],
    ['12,5', 12.5],
    [' 7 ', 7],
  ])('accepts %j', (input, expected) => {
    expect(parsePoints(input)).toBe(expected);
  });

  it.each(['', '-1', '100.01', '101', '12.345', 'abc', '1e2', '.5'])('rejects %j', (input) => {
    expect(parsePoints(input)).toBeNull();
  });
});

describe('roundPoints', () => {
  it('removes float noise from sums', () => {
    expect(roundPoints(0.1 + 0.2)).toBe(0.3);
  });

  it('treats missing values as 0', () => {
    expect(roundPoints(undefined)).toBe(0);
    expect(roundPoints(null)).toBe(0);
  });
});
