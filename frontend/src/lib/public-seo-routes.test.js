import { describe, expect, it } from 'vitest';
import {
  ALL_LOCALIZED_ROUTES,
  APP_PATH_PREFIXES,
  PUBLIC_SEO_ROUTES,
  SOLUTION_SLUGS,
  legacyPublicRedirects,
  resolveLocalizedPath,
  routeForPath,
} from './public-seo-routes.mjs';
import { SOLUTIONS } from './solutions-content';
import { localizePath, localizeHtmlString } from './locale-paths';
import { createVercelConfig } from '../../vercel.mjs';
import { MARKETS, LIVE_COUNTRIES, WAITLIST_COUNTRIES } from './markets.js';

describe('public SEO routes (country-aware marketing)', () => {
  it('has routes for country selector, live countries, and waitlist landing pages with no duplicates', () => {
    // 1 root selector + (LIVE_COUNTRIES * routes * 2 locales) + (WAITLIST_COUNTRIES * 2 locales)
    const expectedTotal = 1 + (LIVE_COUNTRIES.length * PUBLIC_SEO_ROUTES.length * 2) + (WAITLIST_COUNTRIES.length * 2);
    expect(ALL_LOCALIZED_ROUTES).toHaveLength(expectedTotal);

    const paths = ALL_LOCALIZED_ROUTES.map((r) => r.path);
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths).toContain('/');
    expect(paths).toContain('/eg/ar');
    expect(paths).toContain('/eg/en');
    expect(paths).toContain('/eg/en/solutions/whatsapp-sales-system');
    expect(paths).toContain('/sa/ar/pricing');
    expect(paths).toContain('/sa/en/pricing');
    expect(paths).toContain('/ae/ar');
    expect(paths).toContain('/qa/en');
  });

  it('keeps solution slugs and solution copy in sync', () => {
    expect([...SOLUTION_SLUGS].sort()).toEqual(Object.keys(SOLUTIONS).sort());
  });

  it('resolves country, locale and base path from a URL', () => {
    // Legacy URLs (backward compatibility)
    expect(resolveLocalizedPath('/en')).toMatchObject({ locale: 'en', basePath: '/', country: 'eg', isLegacy: true });
    expect(resolveLocalizedPath('/en/pricing/')).toMatchObject({ locale: 'en', basePath: '/pricing', country: 'eg', isLegacy: true });
    expect(resolveLocalizedPath('/pricing')).toMatchObject({ locale: 'ar', basePath: '/pricing', country: 'eg', isLegacy: true });

    // New Country-aware URLs
    expect(resolveLocalizedPath('/')).toMatchObject({ isSelector: true, basePath: '/' });
    expect(resolveLocalizedPath('/eg/ar/pricing')).toMatchObject({ country: 'eg', locale: 'ar', basePath: '/pricing', isLive: true });
    expect(resolveLocalizedPath('/sa/en/pricing')).toMatchObject({ country: 'sa', locale: 'en', basePath: '/pricing', isLive: true });
    expect(resolveLocalizedPath('/ae/ar')).toMatchObject({ country: 'ae', locale: 'ar', basePath: '/', isWaitlist: true });
    expect(resolveLocalizedPath('/qa/en')).toMatchObject({ country: 'qa', locale: 'en', basePath: '/', isWaitlist: true });

    // Route matching
    expect(routeForPath('/eg/en/solutions/unified-inbox')).toMatchObject({ key: 'solution:unified-inbox', locale: 'en', country: 'eg' });
    expect(routeForPath('/sa/ar/pricing')).toMatchObject({ key: 'pricing', locale: 'ar', country: 'sa' });
    expect(routeForPath('/nonexistent')).toBeNull();
    expect(routeForPath('/en/nonexistent')).toBeNull();
    expect(routeForPath('/xx/en/pricing')).toBeNull(); // Unknown country
  });

  it('strictly isolates country-specific capabilities and tax regimes', () => {
    // Saudi-specific capability does not leak to Egypt or Qatar
    expect(MARKETS.sa.capabilities).toContain('mada_payments');
    expect(MARKETS.eg.capabilities).not.toContain('mada_payments');
    expect(MARKETS.qa.capabilities).not.toContain('mada_payments');

    // Egypt-specific capability does not leak to Saudi Arabia
    expect(MARKETS.eg.capabilities).toContain('instapay_reference');
    expect(MARKETS.sa.capabilities).not.toContain('instapay_reference');

    // Qatar has no VAT regime (not 0% VAT)
    expect(MARKETS.qa.taxRegime).toBe('none');
    expect(MARKETS.qa.taxRate).toBeNull();
    expect(MARKETS.eg.taxRegime).toBe('standard');
    expect(MARKETS.eg.taxRate).toBe(0.14);
    expect(MARKETS.sa.taxRegime).toBe('standard');
    expect(MARKETS.sa.taxRate).toBe(0.15);
  });

  it('localizes only public marketing links, inside the visitor\'s own country', () => {
    expect(localizePath('/pricing', 'en')).toBe('/eg/en/pricing');
    expect(localizePath('/pricing', 'ar')).toBe('/eg/ar/pricing');
    expect(localizePath('/', 'en')).toBe('/eg/en');
    expect(localizePath('/pricing?x=1#a', 'en')).toBe('/eg/en/pricing?x=1#a');
    expect(localizePath('/pricing', 'en', 'sa')).toBe('/sa/en/pricing');
    expect(localizePath('/blog/x', 'ar', 'sa')).toBe('/sa/ar/blog/x');
    expect(localizePath('/login', 'en')).toBe('/login');
    // The prerendered HTML carries the default country's links; a visitor on a Saudi page must not
    // be handed Egyptian ones (this is what e2e/seo-localized.spec.js asserts in the browser).
    expect(localizePath('/eg/en/pricing', 'en', 'sa')).toBe('/sa/en/pricing');
    expect(localizePath('/eg/ar/terms', 'ar', 'sa')).toBe('/sa/ar/terms');
    expect(localizePath('/eg', 'en', 'sa')).toBe('/sa');
    expect(localizePath('/sa/en/pricing', 'en', 'sa')).toBe('/sa/en/pricing');
    expect(localizePath('/eg/en/pricing?x=1#a', 'en', 'sa')).toBe('/sa/en/pricing?x=1#a');
    // Without a known country nothing is retargeted, so a caller that cannot know the market
    // cannot silently move a Saudi visitor to Egypt.
    expect(localizePath('/eg/en/pricing', 'en')).toBe('/eg/en/pricing');
    expect(localizePath('/dashboard', 'en', 'sa')).toBe('/dashboard');
    // An old English address keeps its meaning; a prefixed one is left alone.
    expect(localizePath('/en/pricing', 'ar')).toBe('/eg/en/pricing');
    expect(localizePath('/sa/ar/pricing', 'en')).toBe('/sa/ar/pricing');
    expect(localizeHtmlString('<a class="x" href="/product">p</a><a href="/login">l</a>', 'en', 'sa'))
      .toBe('<a class="x" href="/sa/en/product">p</a><a href="/login">l</a>');
  });

  it('redirects every old public address permanently to the default market', () => {
    const redirects = legacyPublicRedirects();
    const bySource = new Map(redirects.map((r) => [r.source, r.destination]));
    expect(bySource.get('/pricing')).toBe('/eg/ar/pricing');
    expect(bySource.get('/en')).toBe('/eg/en');
    expect(bySource.get('/en/solutions/unified-inbox')).toBe('/eg/en/solutions/unified-inbox');
    expect(bySource.has('/')).toBe(false); // `/` is the market selector now
    for (const route of PUBLIC_SEO_ROUTES.filter((r) => r.path !== '/')) {
      expect(bySource.has(route.path), route.path).toBe(true);
      expect(bySource.has(`/en${route.path}`), `/en${route.path}`).toBe(true);
    }
    expect(new Set(redirects.map((r) => r.source)).size).toBe(redirects.length);
    // Old addresses are permanent; the market entry at / is not, because geo
    // detection will change where it points and a 308 would outlive that.
    const configured = createVercelConfig({ environment: 'production' }).redirects;
    const root = configured.find((r) => r.source === '/');
    expect(root).toEqual({ source: '/', destination: '/eg/ar', permanent: false });
    expect(configured.filter((r) => r.source !== '/').every((r) => r.permanent)).toBe(true);
  });
});

describe('vercel rewrites (no soft 404)', () => {
  const config = createVercelConfig({ environment: 'production' });
  const spaRules = config.rewrites.filter((r) => r.destination === '/index.html');
  const toRegex = (source) => new RegExp(`^${source.replace(/:path\*/g, '.*')}$`);
  const matchesSpa = (pathname) => spaRules.some((r) => toRegex(r.source).test(pathname));

  it('does not rewrite arbitrary paths to the SPA shell', () => {
    for (const bad of ['/nonexistent', '/en/nonexistent', '/blogs', '/blog/unknown-post', '/llms.txt.bak', '/wp-admin', '/pricing/extra']) {
      expect(matchesSpa(bad), bad).toBe(false);
    }
  });

  it('still serves every app and auth screen through the SPA', () => {
    for (const prefix of APP_PATH_PREFIXES) {
      expect(matchesSpa(`/${prefix}`), prefix).toBe(true);
      expect(matchesSpa(`/${prefix}/child`), prefix).toBe(true);
    }
  });

  it('keeps the API and auth proxies', () => {
    expect(config.rewrites.some((r) => r.source === '/api/v1/:path*')).toBe(true);
    expect(config.rewrites.some((r) => r.source === '/auth/:path*')).toBe(true);
  });
});
