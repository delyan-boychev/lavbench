import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

/** The setup shared by the app and its test: detection order, languages and file path. */
export const i18nOptions = {
  fallbackLng: 'en',
  // A browser locale such as bg-BG maps to bg without a request for a bg-BG file
  supportedLngs: ['en', 'bg'],
  nonExplicitSupportedLngs: true,
  load: /** @type {const} */ ('languageOnly'),
  debug: false,
  detection: {
    order: ['localStorage', 'navigator'],
    lookupLocalStorage: 'i18nextLng',
    caches: ['localStorage'],
  },
  interpolation: {
    escapeValue: false, // React handles escaping natively
  },
  backend: {
    loadPath: '/locales/{{lng}}/translation.json',
  },
};

i18n.use(HttpBackend).use(LanguageDetector).use(initReactI18next).init(i18nOptions);

// Keep <html lang> in step with the UI language for screen readers and hyphenation
function syncHtmlLang(lng) {
  if (typeof document === 'undefined' || !lng) return;
  document.documentElement.lang = lng.split('-')[0];
}

i18n.on('languageChanged', syncHtmlLang);
syncHtmlLang(i18n.resolvedLanguage || i18n.language);

export default i18n;
