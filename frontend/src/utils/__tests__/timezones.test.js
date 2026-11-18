import { describe, expect, it } from 'vitest';
import { TIMEZONES } from '../timezones';

describe('TIMEZONES', () => {
  it('offers UTC, the default of every competition, exactly once', () => {
    expect(TIMEZONES.filter((zone) => zone.value === 'UTC')).toHaveLength(1);
  });
});
