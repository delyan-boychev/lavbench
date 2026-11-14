import { describe, it, expect, vi, afterEach } from 'vitest';
import { withJitter } from '../jitter';

describe('withJitter', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('spans exactly plus or minus 30%', () => {
    vi.spyOn(Math, 'random').mockReturnValueOnce(0).mockReturnValueOnce(0.5);
    expect(withJitter(1000)).toBe(700);
    expect(withJitter(1000)).toBe(1000);
  });

  it('stays within plus or minus 30%', () => {
    for (let i = 0; i < 200; i += 1) {
      const value = withJitter(1000);
      expect(value).toBeGreaterThanOrEqual(700);
      expect(value).toBeLessThanOrEqual(1300);
    }
  });
});
