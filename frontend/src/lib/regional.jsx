import React, { createContext, useContext, useState, useMemo, useEffect } from "react";

// Country / market profiles. Designed so adding a country is a configuration,
// not a redesign. Currency is part of the regional profile, not the UI language.
export const COUNTRIES = {
  EG: {
    code: "EG",
    name: "Egypt",
    nameAr: "مصر",
    currency: "EGP",
    currencyName: "Egyptian Pound",
    currencyNameAr: "الجنيه المصري",
    timezone: "Africa/Cairo",
    weekStart: "saturday",
    phoneCode: "+20",
    dateLocale: "en-GB",
  },
  SA: {
    code: "SA",
    name: "Saudi Arabia",
    nameAr: "السعودية",
    currency: "SAR",
    currencyName: "Saudi Riyal",
    currencyNameAr: "الريال السعودي",
    timezone: "Asia/Riyadh",
    weekStart: "sunday",
    phoneCode: "+966",
    dateLocale: "en-GB",
  },
  AE: {
    code: "AE",
    name: "United Arab Emirates",
    nameAr: "الإمارات",
    currency: "AED",
    currencyName: "UAE Dirham",
    currencyNameAr: "الدرهم الإماراتي",
    timezone: "Asia/Dubai",
    weekStart: "sunday",
    phoneCode: "+971",
    dateLocale: "en-GB",
  },
  QA: {
    code: "QA",
    name: "Qatar",
    nameAr: "قطر",
    currency: "QAR",
    currencyName: "Qatari Riyal",
    currencyNameAr: "الريال القطري",
    timezone: "Asia/Qatar",
    weekStart: "sunday",
    phoneCode: "+974",
    dateLocale: "en-GB",
  },
  KW: {
    code: "KW",
    name: "Kuwait",
    nameAr: "الكويت",
    currency: "KWD",
    currencyName: "Kuwaiti Dinar",
    currencyNameAr: "الدينار الكويتي",
    timezone: "Asia/Kuwait",
    weekStart: "sunday",
    phoneCode: "+965",
    dateLocale: "en-GB",
  },
  JO: {
    code: "JO",
    name: "Jordan",
    nameAr: "الأردن",
    currency: "JOD",
    currencyName: "Jordanian Dinar",
    currencyNameAr: "الدينار الأردني",
    timezone: "Asia/Amman",
    weekStart: "saturday",
    phoneCode: "+962",
    dateLocale: "en-GB",
  },
  MA: {
    code: "MA",
    name: "Morocco",
    nameAr: "المغرب",
    currency: "MAD",
    currencyName: "Moroccan Dirham",
    currencyNameAr: "الدرهم المغربي",
    timezone: "Africa/Casablanca",
    weekStart: "saturday",
    phoneCode: "+212",
    dateLocale: "en-GB",
  },
};

export const DEFAULT_COUNTRY_CODE = "EG";
const STORAGE_KEY = "salesos.country";

// Module-level active regional config so the free-function formatters stay
// usable from any component without prop-drilling. The provider keeps it in sync.
let activeCurrency = COUNTRIES[DEFAULT_COUNTRY_CODE].currency;
let activeLocale = COUNTRIES[DEFAULT_COUNTRY_CODE].dateLocale;

export function setRegionalConfig({ currency, dateLocale } = {}) {
  if (currency) activeCurrency = currency;
  if (dateLocale) activeLocale = dateLocale;
}

// Locale-aware currency formatter. No hardcoded symbols.
// Uses Latin digits for stable layout in both languages (LTR always).
export function formatCurrency(n, compact = false, currency = activeCurrency) {
  const opts = compact
    ? { notation: "compact", maximumFractionDigits: 1 }
    : { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 };
  try {
    return new Intl.NumberFormat(activeLocale, {
      style: "currency",
      currency,
      ...opts,
    }).format(n);
  } catch {
    return `${currency} ${n.toLocaleString(activeLocale)}`;
  }
}

export function formatNumber(n) {
  return new Intl.NumberFormat(activeLocale).format(n);
}

export function formatDate(d, opts) {
  return new Intl.DateTimeFormat(activeLocale, opts || { day: "numeric", month: "short", year: "numeric" }).format(new Date(d));
}

const RegionalContext = createContext(null);

export function RegionalProvider({ children }) {
  const [countryCode, setCountryCode] = useState(() => {
    if (typeof window === "undefined") return DEFAULT_COUNTRY_CODE;
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_COUNTRY_CODE;
  });

  const country = COUNTRIES[countryCode] || COUNTRIES[DEFAULT_COUNTRY_CODE];

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, countryCode);
    setRegionalConfig({ currency: country.currency, dateLocale: country.dateLocale });
  }, [countryCode]);

  const value = useMemo(
    () => ({ countryCode, setCountryCode, country, countries: COUNTRIES }),
    [countryCode, country]
  );
  return <RegionalContext.Provider value={value}>{children}</RegionalContext.Provider>;
}

export function useRegional() {
  const ctx = useContext(RegionalContext);
  if (!ctx) throw new Error("useRegional must be used within RegionalProvider");
  return ctx;
}
