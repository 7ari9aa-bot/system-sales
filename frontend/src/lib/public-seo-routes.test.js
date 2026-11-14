import { describe, expect, it } from 'vitest';
import {
  ALL_LOCALIZED_ROUTES,
  APP_PATH_PREFIXES,
  PUBLIC_SEO_ROUTES,
  SOLUTION_SLUGS,
  resolveLocalizedPath,
  routeForPath,
} from './public-seo-routes.mjs';
import { SOLUTIONS } from './solutions-content';
import { localizePath, localizeHtmlString } from './locale-paths';
import { createVercelConfig } from '../../vercel.mjs';

describe('public SEO routes', () => {
  it('has an Arabic and an English URL for every route, with no duplicates', () => {
    expect(ALL_LOCALIZED_ROUTES).toHaveLength(PUBLIC_SEO_ROUTES.length * 2);
    const paths = ALL_LOCALIZED_ROUTES.map((r) => r.path);
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths).toContain('/');
    expect(paths).toContain('/en');
    expect(paths).toContain('/en/solutions/whatsapp-sales-system');
  });

  it('keeps solution slugs and solution copy in sync', () => {
    expect([...SOLUTION_SLUGS].sort()).toEqual(Object.keys(SOLUTIONS).sort());
  });

  it('resolves locale and base path from a URL', () => {
    expect(resolveLocalizedPath('/en')).toEqual({ locale: 'en', basePath: '/' });
    expect(resolveLocalizedPath('/en/pricing/')).toEqual({ locale: 'en', basePath: '/pricing' });
    expect(resolveLocalizedPath('/pricing')).toEqual({ locale: 'ar', basePath: '/pricing' });
    expect(routeForPath('/en/solutions/unified-inbox')).toMatchObject({ key: 'solution:unified-inbox', locale: 'en' });
    expect(routeForPath('/nonexistent')).toBeNull();
    expect(routeForPath('/en/nonexistent')).toBeNull();
  });

  it('localizes only public marketing links', () => {
    expect(localizePath('/pricing', 'en')).toBe('/en/pricing');
    expect(localizePath('/', 'en')).toBe('/en');
    expect(localizePath('/pricing?x=1#a', 'en')).toBe('/en/pricing?x=1#a');
    expect(localizePath('/login', 'en')).toBe('/login');
    expect(localizePath('/dashboard', 'en')).toBe('/dashboard');
    expect(localizePath('/pricing', 'ar')).toBe('/pricing');
    expect(localizePath('/en/pricing', 'en')).toBe('/en/pricing');
    expect(localizeHtmlString('<a class="x" href="/product">p</a><a href="/login">l</a>', 'en'))
      .toBe('<a class="x" href="/en/product">p</a><a href="/login">l</a>');
  });
});

describe('vercel rewrites (no soft 404)', () => {
  const config = createVercelConfig({ environment: 'production' });
  const spaRules = config.rewrites.filter((r) => r.destination === '/index.html');
  const toRegex = (source) => new RegExp(`^${source.replace(/:path\*/g, '.*')}$`);
  const matchesSpa = (pathname) => spaRules.some((r) => toRegex(r.source).test(pathname));

  it('does not rewrite arbitrary paths to the SPA shell', () => {
    for (const bad of ['/nonexistent', '/en/nonexistent', '/blog', '/llms.txt.bak', '/wp-admin', '/pricing/extra']) {
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
