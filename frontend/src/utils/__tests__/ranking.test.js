import { describe, it, expect } from 'vitest';
import { compactRanks } from '../ranking';

const e = (rank, extra = {}) => ({ rank, has_submitted: true, ...extra });

describe('compactRanks', () => {
  it('keeps tied ranks tied', () => {
    expect(compactRanks([e(1), e(1), e(3)]).map((x) => x.rank)).toEqual([1, 1, 3]);
  });

  it('closes gaps left by removed entries without breaking ties', () => {
    // Backend ranks 2 was a removed baseline
    expect(compactRanks([e(1), e(3), e(3), e(5)]).map((x) => x.rank)).toEqual([1, 2, 2, 4]);
  });

  it('nulls ranks for entries without submissions', () => {
    const out = compactRanks([e(1), e(null), { rank: 2, has_submitted: false }]);
    expect(out.map((x) => x.rank)).toEqual([1, null, null]);
  });
});
