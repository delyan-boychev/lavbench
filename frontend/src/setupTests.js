import '@testing-library/jest-dom';
import { vi } from 'vitest';
import mockEnTranslation from '../public/locales/en/translation.json';

vi.mock('react-i18next', () => {
  const React = require('react');
  // Define helper inside or access it since it starts with mock
  const getTranslationVal = (key, count) => {
    const lookup = (k) => {
      const parts = k.split('.');
      let current = mockEnTranslation;
      for (const part of parts) {
        if (current && typeof current === 'object') {
          current = current[part];
        } else {
          return undefined;
        }
      }
      return current;
    };

    if (count !== undefined) {
      const suffix = count === 1 ? '_one' : '_other';
      const val = lookup(key + suffix);
      if (val !== undefined) return val;
    }
    return lookup(key);
  };

  const useTranslationMock = () => ({
    t: (key, options) => {
      const count = options && typeof options === 'object' ? options.count : undefined;
      let value = /** @type {string|any} */ (getTranslationVal(key, count));
      if (value === undefined) {
        return key;
      }
      if (options && typeof options === 'object') {
        Object.keys(options).forEach((optKey) => {
          if (typeof value === 'string') {
            value = value.replace(new RegExp(`{{${optKey}}}`, 'g'), options[optKey]);
          }
        });
      }
      return value;
    },
    i18n: {
      changeLanguage: vi.fn().mockImplementation(() => Promise.resolve()),
      language: 'en',
    },
  });

  return {
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
    initReactI18next: {
      type: '3rdParty',
      init: () => {},
    },
  };
});
