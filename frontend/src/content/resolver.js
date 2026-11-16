/**
 * 3-tier content resolver for the country-aware marketing site.
 *
 * Hierarchy:
 * 1. Country Override: content/{country}/{lang}
 * 2. Shared Content: content/shared
 * Rule: NEVER fall back to another country.
 * Rule: Capabilities must have published: true before appearing on the public site.
 */

import { sharedContent } from './shared.js';
import { egAr } from './eg/ar.js';
import { egEn } from './eg/en.js';
import { saAr } from './sa/ar.js';
import { saEn } from './sa/en.js';
import { aeAr } from './ae/ar.js';
import { aeEn } from './ae/en.js';
import { qaAr } from './qa/ar.js';
import { qaEn } from './qa/en.js';
import { getMarket } from '../lib/markets.js';

const OVERRIDES = {
  eg: { ar: egAr, en: egEn },
  sa: { ar: saAr, en: saEn },
  ae: { ar: aeAr, en: aeEn },
  qa: { ar: qaAr, en: qaEn },
};

/**
 * Feature release gate for public claims.
 * Unreleased items (e.g. ZATCA e-invoicing Phase 2, ETA Egypt receipt platform)
 * are published: false so they never appear on marketing pages until verified.
 */
export const CAPABILITY_PUBLISH_STATUS = {
  // Verified live capabilities
  instapay_reference: true,
  fawry_payments: true,
  vodafone_cash: true,
  bosta_shipping: true,
  governorate_address: true,
  national_address: true,
  mada_payments: true,
  stc_pay: true,
  tamara_bnpl: true,
  tabby_bnpl: true,
  smsa_shipping: true,
  apple_pay: true,
  emirates_address: true,
  qatar_zones: true,
  qpay_payments: true,
  naps_debit: true,

  // Deferred / in-progress compliance features — MUST NOT be advertised
  einvoice_zatca: false,
  einvoice_eta: false,
  peppol_ae: false,
};

/**
 * Resolve a content section for a specific country and language.
 * Follows strict override -> shared fallback order with no cross-country leakage.
 */
export function resolveContent(country, locale = 'ar', section = 'hero') {
  const cCode = (country || 'eg').toLowerCase();
  const lang = locale === 'en' ? 'en' : 'ar';

  const countryOverride = OVERRIDES[cCode]?.[lang]?.[section];
  const shared = sharedContent[lang]?.[section];

  if (!countryOverride) {
    return shared;
  }

  if (typeof countryOverride === 'object' && !Array.isArray(countryOverride)) {
    return { ...shared, ...countryOverride };
  }

  return countryOverride;
}

/**
 * Return FAQ items relevant to this country, merging country questions with shared questions.
 */
export function resolveFaq(country, locale = 'ar') {
  const cCode = (country || 'eg').toLowerCase();
  const lang = locale === 'en' ? 'en' : 'ar';

  const countryFaq = OVERRIDES[cCode]?.[lang]?.faq || [];
  const sharedFaq = sharedContent[lang]?.faq || [];

  return [...countryFaq, ...sharedFaq];
}

/**
 * Check if a country has a specific capability AND that capability is verified for publication.
 */
export function canPublishCapability(country, capability) {
  if (!CAPABILITY_PUBLISH_STATUS[capability]) {
    return false;
  }
  const market = getMarket(country);
  return Boolean(market?.capabilities?.includes(capability));
}
