import '@testing-library/jest-dom';
import { vi } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import mockEnTranslation from '../public/locales/en/translation.json';

const server = setupServer(
  http.get('/locales/:lang/translation.json', () => {
    return HttpResponse.json(mockEnTranslation);
  }),
);

server.listen({ onUnhandledRequest: 'bypass' });

vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
});

// The test DOM does not scroll; editors and lists call it to bring content into view
window.scrollTo = vi.fn();

vi.stubGlobal(
  'EventSource',
  class {
    constructor(url) {
      this.url = url;
    }
    close() {}
    onmessage = null;
    onerror = null;
  },
);

vi.mock('react-i18next', async (importOriginal) => {
  // 1. Inherit all standard exports (crucial for initReactI18next)
  const actual = /** @type {Record<string, unknown>} */ (await importOriginal());

  // 2. Dynamically import React to avoid ESM require() crashes
  const React = await import('react');

  const useTranslationMock = () => ({
    t: (key, options) => {
      // Basic fallback logic for translations
      const parts = key.split('.');
      let current = mockEnTranslation;
      let parent = null;
      for (const part of parts) {
        if (current && typeof current === 'object') {
          parent = current;
          current = current[part];
        } else {
          return key;
        }
      }
      // i18next plurals: with a count, `key` resolves to `key_one` or `key_other` (English
      // rules) before the base key
      if (parent && typeof options?.count === 'number') {
        const suffix = options.count === 1 ? 'one' : 'other';
        current = parent[`${parts[parts.length - 1]}_${suffix}`] ?? current;
      }
      let value = typeof current === 'string' ? current : key;

      // Handle simple interpolation if options exist
      if (options && typeof options === 'object') {
        Object.keys(options).forEach((optKey) => {
          value = value.replace(new RegExp(`{{${optKey}}}`, 'g'), options[optKey]);
        });
      }
      return value;
    },
    i18n: {
      changeLanguage: vi.fn().mockResolvedValue(),
      language: 'en',
    },
  });

  return {
    ...actual, // <--- This provides initReactI18next to your app
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: useTranslationMock,
    withTranslation: () => (Component) => {
      const Wrapped = (props) => {
        const { t, i18n } = useTranslationMock();
        return React.createElement(Component, { t, i18n, ...props });
      };
      return Wrapped;
    },
    Trans: ({ i18nKey }) => {
      const parts = i18nKey.split('.');
      let current = mockEnTranslation;
      for (const part of parts) {
        if (current && typeof current === 'object') {
          current = current[part];
        } else {
          return i18nKey;
        }
      }
      return typeof current === 'string' ? current : i18nKey;
    },
  };
});
