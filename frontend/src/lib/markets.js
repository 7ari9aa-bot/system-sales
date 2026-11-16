/**
 * Client-side Market Specifications — aligned with backend CountrySpec.
 * Single source of truth for countries, currencies, and launch statuses on the web client.
 */

export const MARKETS = {
  eg: {
    code: 'EG',
    slug: 'eg',
    nameAr: 'مصر',
    nameEn: 'Egypt',
    flag: '🇪🇬',
    currency: 'EGP',
    symbolAr: 'ج.م',
    symbolEn: 'EGP',
    decimals: 2,
    phoneCode: '+20',
    launchStatus: 'live',
    defaultTimezone: 'Africa/Cairo',
    localeAr: 'ar-EG',
    localeEn: 'en-EG',
    taxRegime: 'standard',
    taxRate: 0.14,
    taxAuthorityAr: 'مصلحة الضرائب المصرية',
    taxAuthorityEn: 'Egyptian Tax Authority',
    capabilities: ['governorate_address', 'instapay_reference', 'fawry_payments', 'vodafone_cash', 'bosta_shipping'],
    legalUrls: {
      terms: '/eg/ar/terms',
      privacy: '/eg/ar/privacy',
      contactSales: '/eg/ar/contact-sales',
    },
  },
  sa: {
    code: 'SA',
    slug: 'sa',
    nameAr: 'المملكة العربية السعودية',
    nameEn: 'Saudi Arabia',
    flag: '🇸🇦',
    currency: 'SAR',
    symbolAr: 'ر.س',
    symbolEn: 'SAR',
    decimals: 2,
    phoneCode: '+966',
    launchStatus: 'live',
    defaultTimezone: 'Asia/Riyadh',
    localeAr: 'ar-SA',
    localeEn: 'en-SA',
    taxRegime: 'standard',
    taxRate: 0.15,
    taxAuthorityAr: 'هيئة الزكاة والضريبة والجمارك',
    taxAuthorityEn: 'ZATCA',
    capabilities: ['national_address', 'mada_payments', 'stc_pay', 'tamara_bnpl', 'tabby_bnpl', 'smsa_shipping'],
    legalUrls: {
      terms: '/sa/ar/terms',
      privacy: '/sa/ar/privacy',
      contactSales: '/sa/ar/contact-sales',
    },
  },
  ae: {
    code: 'AE',
    slug: 'ae',
    nameAr: 'الإمارات العربية المتحدة',
    nameEn: 'United Arab Emirates',
    flag: '🇦🇪',
    currency: 'AED',
    symbolAr: 'د.إ',
    symbolEn: 'AED',
    decimals: 2,
    phoneCode: '+971',
    launchStatus: 'waitlist',
    defaultTimezone: 'Asia/Dubai',
    localeAr: 'ar-AE',
    localeEn: 'en-AE',
    taxRegime: 'standard',
    taxRate: 0.05,
    taxAuthorityAr: 'الهيئة الاتحادية للضرائب',
    taxAuthorityEn: 'Federal Tax Authority',
    capabilities: ['emirates_address', 'tabby_bnpl', 'tamara_bnpl', 'apple_pay'],
    legalUrls: {
      terms: '/ae/ar/terms',
      privacy: '/ae/ar/privacy',
      contactSales: '/ae/ar/contact-sales',
    },
  },
  qa: {
    code: 'QA',
    slug: 'qa',
    nameAr: 'دولة قطر',
    nameEn: 'Qatar',
    flag: '🇶🇦',
    currency: 'QAR',
    symbolAr: 'ر.ق',
    symbolEn: 'QAR',
    decimals: 2,
    phoneCode: '+974',
    launchStatus: 'waitlist',
    defaultTimezone: 'Asia/Qatar',
    localeAr: 'ar-QA',
    localeEn: 'en-QA',
    // Qatar has no general VAT regime in 2026.
    taxRegime: 'none',
    taxRate: null,
    taxAuthorityAr: 'الهيئة العامة للضرائب',
    taxAuthorityEn: 'General Tax Authority',
    capabilities: ['qatar_zones', 'qpay_payments', 'naps_debit'],
    legalUrls: {
      terms: '/qa/ar/terms',
      privacy: '/qa/ar/privacy',
      contactSales: '/qa/ar/contact-sales',
    },
  },
};

export const SUPPORTED_COUNTRY_SLUGS = Object.keys(MARKETS);
export const DEFAULT_COUNTRY_SLUG = 'eg';

export const LIVE_COUNTRIES = Object.values(MARKETS).filter((m) => m.launchStatus === 'live');
export const WAITLIST_COUNTRIES = Object.values(MARKETS).filter((m) => m.launchStatus === 'waitlist');

export function getMarket(slug) {
  if (!slug) return null;
  return MARKETS[slug.toLowerCase()] || null;
}

export function isSupportedCountry(slug) {
  return Boolean(slug && MARKETS[slug.toLowerCase()]);
}

export function isCountryLive(slug) {
  const m = getMarket(slug);
  return m ? m.launchStatus === 'live' : false;
}

export function isCountryWaitlist(slug) {
  const m = getMarket(slug);
  return m ? m.launchStatus === 'waitlist' : false;
}

/**
 * Format a numeric amount using the market currency and language.
 */
export function formatMarketPrice(amount, marketSlug, locale = 'ar') {
  const market = getMarket(marketSlug) || MARKETS[DEFAULT_COUNTRY_SLUG];
  const num = Number(amount) || 0;
  const numLocale = locale === 'ar' ? market.localeAr : market.localeEn;

  try {
    const formatted = new Intl.NumberFormat(numLocale, {
      minimumFractionDigits: num % 1 === 0 ? 0 : market.decimals,
      maximumFractionDigits: market.decimals,
    }).format(num);

    const symbol = locale === 'ar' ? market.symbolAr : market.symbolEn;
    return locale === 'ar' ? `${formatted} ${symbol}` : `${symbol} ${formatted}`;
  } catch {
    const symbol = locale === 'ar' ? market.symbolAr : market.symbolEn;
    return `${num} ${symbol}`;
  }
}
