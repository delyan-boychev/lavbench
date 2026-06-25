import '@testing-library/jest-dom';
import { vi } from 'vitest';
import mockEnTranslation from '../public/locales/en/translation.json';

vi.mock('react-i18next', async (importOriginal) => {
  // 1. Inherit all standard exports (crucial for initReactI18next)
  const actual = await importOriginal();

  // 2. Dynamically import React to avoid ESM require() crashes
  const React = await import('react');

  const useTranslationMock = () => ({
    t: (key, options) => {
      // Basic fallback logic for translations
      const parts = key.split('.');
      let current = mockEnTranslation;
      for (const part of parts) {
        if (current && typeof current === 'object') {
          current = current[part];
        } else {
          return key;
        }
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
