import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import i18next from 'i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';
import { i18nOptions } from '../i18n';

// A language counts as resolved only once it has a translation, so the stub returns one
/** A fresh i18next with the app's options, the real detector and a recording backend. */
async function start() {
  const requested = [];
  const instance = i18next.createInstance();
  await instance
    .use(HttpBackend)
    .use(LanguageDetector)
    .init({
      ...i18nOptions,
      backend: {
        ...i18nOptions.backend,
        request: (_options, url, _payload, callback) => {
          requested.push(url);
          callback(null, { status: 200, data: '{"hello": "x"}' });
        },
      },
    });
  return { instance, requested };
}

function browserLanguage(language) {
  vi.spyOn(window.navigator, 'language', 'get').mockReturnValue(language);
  vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue([language]);
}

// setupTests stubs localStorage with mocks; a saved choice is what getItem returns
function savedLanguage(language) {
  vi.mocked(window.localStorage.getItem).mockImplementation((key) =>
    key === 'i18nextLng' ? language : null,
  );
}

describe('i18n language detection', () => {
  beforeEach(() => savedLanguage(null));
  afterEach(() => {
    vi.restoreAllMocks();
    savedLanguage(null);
  });

  it('maps a regional Bulgarian browser to bg without asking for a bg-BG file', async () => {
    browserLanguage('bg-BG');
    const { instance, requested } = await start();
    expect(instance.resolvedLanguage).toBe('bg');
    // The en fallback is loaded too, for keys bg lacks; no bg-BG file is ever asked for
    expect(requested).toEqual(['/locales/bg/translation.json', '/locales/en/translation.json']);
  });

  it('maps a regional English browser to en', async () => {
    browserLanguage('en-US');
    const { instance, requested } = await start();
    expect(instance.resolvedLanguage).toBe('en');
    expect(requested).toEqual(['/locales/en/translation.json']);
  });

  it('falls back to en for an unsupported language', async () => {
    browserLanguage('de-DE');
    const { instance, requested } = await start();
    expect(instance.resolvedLanguage).toBe('en');
    expect(requested).toEqual(['/locales/en/translation.json']);
  });

  it('prefers the saved choice to the browser language', async () => {
    browserLanguage('en-US');
    savedLanguage('bg');
    const { instance, requested } = await start();
    expect(instance.resolvedLanguage).toBe('bg');
    expect(requested).not.toContain('/locales/en-US/translation.json');
  });
});
