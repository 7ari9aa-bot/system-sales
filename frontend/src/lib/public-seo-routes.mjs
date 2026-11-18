// Single source of truth for every public, indexable URL.
//
// Structured by Country and Language: `/{country}/{lang}/...`
// Supports multiple markets (EG, SA, AE, QA).
// `LIVE_COUNTRY_SLUGS` receive full localized pages.
// `WAITLIST_COUNTRY_SLUGS` receive dedicated waitlist landing pages.
// Root `/` is the country and language selector.

export const SITE_ORIGIN = 'https://fihrist.world';

// Core public pages
const CORE_KEYS = [
  ['/', 'home'],
  ['/product', 'product'],
  ['/conversations', 'conversations'],
  ['/context', 'context'],
  ['/assistant', 'assistant'],
  ['/automation', 'automation'],
  ['/pricing', 'pricing'],
  ['/security', 'security'],
  ['/privacy', 'privacy'],
  ['/terms', 'terms'],
  ['/contact-sales', 'contact-sales'],
  ['/support', 'support'],
];

// Keyword landing pages
export const SOLUTION_SLUGS = [
  'whatsapp-sales-system',
  'inventory-management-system',
  'ai-sales-assistant',
  'unified-inbox',
  'pos-cashier-system',
  'sales-crm-for-stores',
  'order-management-system',
];

// Blog articles
export const BLOG_SLUGS = [
  'how-to-sell-on-whatsapp-organized',
  'inventory-tracking-for-small-stores',
  'crm-vs-order-log-difference',
  'reply-to-customers-faster-unified-inbox',
  'follow-up-customers-who-went-quiet',
  'prevent-overselling-and-stockouts',
  'whatsapp-order-taking-checklist',
  'ai-assistant-for-store-customer-replies',
  'pos-for-small-shops-what-to-look-for',
  'sales-report-basics-for-store-owners',
];

export const LOCALES = ['ar', 'en'];
export const DEFAULT_LOCALE = 'ar';

export const COUNTRY_SLUGS = ['eg', 'sa', 'ae', 'qa'];
export const LIVE_COUNTRY_SLUGS = ['eg', 'sa'];
export const WAITLIST_COUNTRY_SLUGS = ['ae', 'qa'];
export const DEFAULT_COUNTRY = 'eg';

export const HREFLANG_CODES = {
  'eg:ar': 'ar-EG',
  'eg:en': 'en-EG',
  'sa:ar': 'ar-SA',
  'sa:en': 'en-SA',
  'ae:ar': 'ar-AE',
  'ae:en': 'en-AE',
  'qa:ar': 'ar-QA',
  'qa:en': 'en-QA',
};

/** Base Arabic route catalog: [{ path, key }]. */
export const PUBLIC_SEO_ROUTES = [
  ...CORE_KEYS.map(([path, key]) => ({ path, key })),
  ...SOLUTION_SLUGS.map((slug) => ({ path: `/solutions/${slug}`, key: `solution:${slug}` })),
  { path: '/solutions', key: 'solutions' },
  { path: '/blog', key: 'blog' },
  ...BLOG_SLUGS.map((slug) => ({ path: `/blog/${slug}`, key: `post:${slug}` })),
];

export const absoluteUrl = (path) => `${SITE_ORIGIN}${path === '/' ? '/' : path}`;

export function buildLocalizedRoute(country, locale, basePath) {
  const cleanBase = basePath === '/' ? '' : basePath;
  return `/${country}/${locale}${cleanBase}`;
}

/**
 * Generate every indexable route across all live countries and locales,
 * plus waitlist landing pages and the root selector.
 */
function generateAllLocalizedRoutes() {
  const routes = [];

  // Root country/language selector
  routes.push({
    key: 'selector',
    country: null,
    locale: 'ar',
    path: '/',
    basePath: '/',
    arPath: '/',
    enPath: '/',
    isSelector: true,
  });

  // Live countries: full catalog of pages
  for (const country of LIVE_COUNTRY_SLUGS) {
    for (const locale of LOCALES) {
      for (const r of PUBLIC_SEO_ROUTES) {
        const path = buildLocalizedRoute(country, locale, r.path);
        routes.push({
          key: r.key,
          country,
          locale,
          basePath: r.path,
          path,
          arPath: buildLocalizedRoute(country, 'ar', r.path),
          enPath: buildLocalizedRoute(country, 'en', r.path),
          isLive: true,
          isWaitlist: false,
        });
      }
    }
  }

  // Waitlist countries: dedicated waitlist landing page
  for (const country of WAITLIST_COUNTRY_SLUGS) {
    for (const locale of LOCALES) {
      const path = `/${country}/${locale}`;
      routes.push({
        key: `waitlist:${country}`,
        country,
        locale,
        basePath: '/',
        path,
        arPath: `/${country}/ar`,
        enPath: `/${country}/en`,
        isLive: false,
        isWaitlist: true,
      });
    }
  }

  return routes;
}

export const ALL_LOCALIZED_ROUTES = generateAllLocalizedRoutes();

/**
 * Normalise a pathname and extract its country, locale, and base route.
 */
export function resolveLocalizedPath(pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/';
  if (clean === '/') {
    return {
      country: null,
      locale: 'ar',
      basePath: '/',
      isSelector: true,
      isLive: false,
      isWaitlist: false,
      isUnknown: false,
    };
  }

  const segments = clean.split('/').filter(Boolean); // ['eg', 'ar', 'pricing']
  const first = segments[0]?.toLowerCase();
  const second = segments[1]?.toLowerCase();

  // Pattern: /{country}/{locale}/...
  if (COUNTRY_SLUGS.includes(first)) {
    const country = first;
    const isWaitlist = WAITLIST_COUNTRY_SLUGS.includes(country);
    const locale = LOCALES.includes(second) ? second : 'ar';
    const rest = segments.slice(2).join('/');
    const basePath = rest ? `/${rest}` : '/';

    return {
      country,
      locale,
      basePath,
      isSelector: false,
      isLive: !isWaitlist,
      isWaitlist,
      isUnknown: false,
    };
  }

  // Unknown country prefix (e.g. /fr/ar/pricing) -> 404
  if (segments.length >= 2 && LOCALES.includes(second)) {
    return {
      country: first,
      locale: second,
      basePath: `/${segments.slice(2).join('/')}`,
      isSelector: false,
      isLive: false,
      isWaitlist: false,
      isUnknown: true,
    };
  }

  // Legacy route backwards compatibility (/pricing or /en/pricing)
  if (clean === '/en' || clean.startsWith('/en/')) {
    const basePath = clean === '/en' ? '/' : clean.slice(3);
    return {
      country: DEFAULT_COUNTRY,
      locale: 'en',
      basePath,
      isSelector: false,
      isLive: true,
      isWaitlist: false,
      isUnknown: false,
      isLegacy: true,
    };
  }

  return {
    country: DEFAULT_COUNTRY,
    locale: 'ar',
    basePath: clean,
    isSelector: false,
    isLive: true,
    isWaitlist: false,
    isUnknown: false,
    isLegacy: true,
  };
}

export function routeForPath(pathname) {
  const resolved = resolveLocalizedPath(pathname);
  if (resolved.isSelector) {
    return { key: 'selector', ...resolved };
  }
  if (resolved.isWaitlist) {
    return { key: `waitlist:${resolved.country}`, ...resolved };
  }
  if (resolved.isUnknown) {
    return null;
  }
  const route = PUBLIC_SEO_ROUTES.find((r) => r.path === resolved.basePath);
  return route ? { ...route, ...resolved } : null;
}

export const PUBLIC_PATHS = ALL_LOCALIZED_ROUTES.map((r) => r.path);

export const APP_PATH_PREFIXES = [
  'dashboard', 'inbox', 'instagram', 'customers', 'products', 'inventory', 'pos', 'cashier', 'sales',
  'sales-assistant', 'marketing', 'ai', 'analytics', 'owner', 'usage', 'website', 'settings',
  'orders', 'login', 'register', 'forgot-password', 'reset-password', 'verify-email',
  'accept-invitation',
];
