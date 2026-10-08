import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
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
  });

// Keep <html lang> in step with the UI language for screen readers and hyphenation
function syncHtmlLang(lng) {
  if (typeof document === 'undefined' || !lng) return;
  document.documentElement.lang = lng.split('-')[0];
}

i18n.on('languageChanged', syncHtmlLang);
syncHtmlLang(i18n.resolvedLanguage || i18n.language);

export default i18n;
