import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import en from "./locales/en.json";
import ta from "./locales/ta.json";
import si from "./locales/si.json";
import ar from "./locales/ar.json";
import hi from "./locales/hi.json";
import fr from "./locales/fr.json";
import es from "./locales/es.json";
import zh from "./locales/zh.json";
import ja from "./locales/ja.json";
import de from "./locales/de.json";
import ko from "./locales/ko.json";
import pt from "./locales/pt.json";
import ml from "./locales/ml.json";

export const LANGUAGES = [
  { code: "en", name: "English", native: "English", flag: "\u{1F1EC}\u{1F1E7}", rtl: false },
  { code: "ta", name: "Tamil", native: "\u0BA4\u0BAE\u0BBF\u0BB4\u0BCD", flag: "\u{1F1F1}\u{1F1F0}", rtl: false },
  { code: "si", name: "Sinhala", native: "\u0DC3\u0DD2\u0D82\u0DC4\u0DBD", flag: "\u{1F1F1}\u{1F1F0}", rtl: false },
  { code: "ml", name: "Malayalam", native: "\u0D2E\u0D32\u0D2F\u0D3E\u0D33\u0D02", flag: "\u{1F1EE}\u{1F1F3}", rtl: false },
  { code: "ar", name: "Arabic", native: "\u0627\u0644\u0639\u0631\u0628\u064A\u0629", flag: "\u{1F1F8}\u{1F1E6}", rtl: true },
  { code: "hi", name: "Hindi", native: "\u0939\u093F\u0928\u094D\u0926\u0940", flag: "\u{1F1EE}\u{1F1F3}", rtl: false },
  { code: "fr", name: "French", native: "Fran\u00E7ais", flag: "\u{1F1EB}\u{1F1F7}", rtl: false },
  { code: "es", name: "Spanish", native: "Espa\u00F1ol", flag: "\u{1F1EA}\u{1F1F8}", rtl: false },
  { code: "zh", name: "Chinese", native: "\u4E2D\u6587", flag: "\u{1F1E8}\u{1F1F3}", rtl: false },
  { code: "ja", name: "Japanese", native: "\u65E5\u672C\u8A9E", flag: "\u{1F1EF}\u{1F1F5}", rtl: false },
  { code: "de", name: "German", native: "Deutsch", flag: "\u{1F1E9}\u{1F1EA}", rtl: false },
  { code: "ko", name: "Korean", native: "\uD55C\uAD6D\uC5B4", flag: "\u{1F1F0}\u{1F1F7}", rtl: false },
  { code: "pt", name: "Portuguese", native: "Portugu\u00EAs", flag: "\u{1F1E7}\u{1F1F7}", rtl: false },
];

const RTL_LANGUAGES = new Set(LANGUAGES.filter((l) => l.rtl).map((l) => l.code));

function updateDirection(lng) {
  const dir = RTL_LANGUAGES.has(lng) ? "rtl" : "ltr";
  document.documentElement.dir = dir;
  document.documentElement.lang = lng;
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ta: { translation: ta },
      si: { translation: si },
      ml: { translation: ml },
      ar: { translation: ar },
      hi: { translation: hi },
      fr: { translation: fr },
      es: { translation: es },
      zh: { translation: zh },
      ja: { translation: ja },
      de: { translation: de },
      ko: { translation: ko },
      pt: { translation: pt },
    },
    fallbackLng: "en",
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "ada_language",
      caches: ["localStorage"],
    },
  });

// Set initial direction
updateDirection(i18n.language);

// Update direction on language change
i18n.on("languageChanged", updateDirection);

export default i18n;
