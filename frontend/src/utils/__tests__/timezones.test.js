import { afterEach, describe, expect, it, vi } from 'vitest';
import { TIMEZONES, browserTimeZone } from '../timezones';

describe('TIMEZONES', () => {
  it('offers UTC exactly once', () => {
    expect(TIMEZONES.filter((zone) => zone.value === 'UTC')).toHaveLength(1);
  });
});

describe('browserTimeZone', () => {
  afterEach(() => vi.restoreAllMocks());

  const browserIn = (timeZone) =>
    vi
      .spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
      .mockReturnValue(/** @type {any} */ ({ timeZone }));

  it("starts a new competition in the browser's zone", () => {
    browserIn('Europe/Sofia');
    expect(browserTimeZone()).toBe('Europe/Sofia');
  });

  it('falls back to UTC for a zone the list does not offer', () => {
    browserIn('Mars/Olympus_Mons');
    expect(browserTimeZone()).toBe('UTC');
  });
});
