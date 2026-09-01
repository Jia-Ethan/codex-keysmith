import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "./zh-CN.json";
import en from "./en.json";
import { getSettings } from "../lib/settings.js";

i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { translation: zhCN },
    en: { translation: en },
  },
  lng: getSettings().lang,
  fallbackLng: "zh-CN",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

document.documentElement.lang = i18n.language;

export default i18n;
