import { describe, it, expect } from 'vitest';
import { resolveContent, resolveFaq, canPublishCapability } from './resolver.js';
import { MARKETS } from '../lib/markets.js';

describe('Content Layer (3-tier resolution)', () => {
  it('resolves country overrides over shared content', () => {
    const egHero = resolveContent('eg', 'ar', 'hero');
    expect(egHero.kicker).toContain('مصر');
    expect(egHero.title).toContain('شات العميل');

    const saHero = resolveContent('sa', 'ar', 'hero');
    expect(saHero.kicker).toContain('السعودية');
    expect(saHero.title).toContain('الواتساب');
  });

  it('strictly isolates country content and prevents cross-country leakage', () => {
    const egHero = resolveContent('eg', 'ar', 'hero');
    const saHero = resolveContent('sa', 'ar', 'hero');
    const qaHero = resolveContent('qa', 'ar', 'hero');

    // Egyptian content should never leak to Saudi Arabia
    expect(saHero.title).not.toContain('شات العميل على واتساب لحد تسليم الأوردر وكاش المحل');
    expect(saHero.body).not.toContain('بوسطة');
    expect(saHero.body).not.toContain('إنستاباي');

    // Saudi content should never leak to Egypt
    expect(egHero.title).not.toContain('لين إتمام البيع');
    expect(egHero.body).not.toContain('العنوان الوطني');
    expect(egHero.body).not.toContain('مدى');

    // Qatar content should not have Egyptian or Saudi local references
    expect(qaHero.body).not.toContain('بوسطة');
    expect(qaHero.body).not.toContain('مدى');
    expect(qaHero.kicker).toContain('قطر');
  });

  it('falls back to shared content when no country override exists for a section', () => {
    const valueProps = resolveContent('sa', 'ar', 'valueProps');
    expect(Array.isArray(valueProps)).toBe(true);
    expect(valueProps.length).toBeGreaterThan(0);
    expect(valueProps[0].id).toBe('conversations');
  });

  it('resolves country-specific FAQ without cross-contamination', () => {
    const egFaq = resolveFaq('eg', 'ar');
    const saFaq = resolveFaq('sa', 'ar');

    const egIds = egFaq.map((f) => f.id);
    const saIds = saFaq.map((f) => f.id);

    // Egypt has InstaPay & Bosta FAQ
    expect(egIds).toContain('eg_payments');
    expect(egIds).toContain('eg_shipping');
    expect(saIds).not.toContain('eg_payments');
    expect(saIds).not.toContain('eg_shipping');

    // Saudi has Mada & National Address FAQ
    expect(saIds).toContain('sa_payments');
    expect(saIds).toContain('sa_address');
    expect(egIds).not.toContain('sa_payments');
    expect(egIds).not.toContain('sa_address');

    // Both contain shared general questions
    expect(egIds).toContain('what_is_fihrist');
    expect(saIds).toContain('what_is_fihrist');
  });

  it('strictly respects the capability publish gate (no unverified compliance claims)', () => {
    // Verified capabilities
    expect(canPublishCapability('eg', 'instapay_reference')).toBe(true);
    expect(canPublishCapability('sa', 'mada_payments')).toBe(true);
    expect(canPublishCapability('eg', 'mada_payments')).toBe(false);

    // Unreleased / in-progress e-invoicing capabilities MUST NOT be published
    expect(canPublishCapability('sa', 'einvoice_zatca')).toBe(false);
    expect(canPublishCapability('eg', 'einvoice_eta')).toBe(false);
    expect(canPublishCapability('ae', 'peppol_ae')).toBe(false);
  });

  it('provides country-specific legal URLs for each market', () => {
    for (const [slug, market] of Object.entries(MARKETS)) {
      expect(market.legalUrls).toBeDefined();
      expect(market.legalUrls.terms).toBe(`/${slug}/ar/terms`);
      expect(market.legalUrls.privacy).toBe(`/${slug}/ar/privacy`);
      expect(market.legalUrls.contactSales).toBe(`/${slug}/ar/contact-sales`);
    }
  });
});
