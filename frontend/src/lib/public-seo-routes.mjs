// Single source of truth for every public, indexable URL.
//
// `PUBLIC_SEO_ROUTES` keeps its original shape (Arabic, unprefixed paths) so
// existing callers keep working. English lives under `/en/...` and every
// route is generated here, so sitemap, hreflang, prerender, the SPA router
// and the Vercel rewrite allow-list can never drift apart.

export const SITE_ORIGIN = 'https://fihrist.world';

// Pages that already exist in the app.
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

// Keyword landing pages (Arabic + English copy lives in solutions-content.js).
export const SOLUTION_SLUGS = [
  'whatsapp-sales-system',
  'inventory-management-system',
  'ai-sales-assistant',
  'unified-inbox',
  'pos-cashier-system',
  'sales-crm-for-stores',
  'order-management-system',
];

// Blog articles. Copy lives in blog-content.js; the slug list lives here so the
// sitemap, hreflang, prerender and the Vercel allow-list stay in sync.
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

const withLocale = (path, locale) => {
  if (locale === 'ar') return path;
  return path === '/' ? '/en' : `/en${path}`;
};

/** Arabic route list, unchanged shape: [{ path, key }]. */
export const PUBLIC_SEO_ROUTES = [
  ...CORE_KEYS.map(([path, key]) => ({ path, key })),
  ...SOLUTION_SLUGS.map((slug) => ({ path: `/solutions/${slug}`, key: `solution:${slug}` })),
  { path: '/solutions', key: 'solutions' },
  { path: '/blog', key: 'blog' },
  ...BLOG_SLUGS.map((slug) => ({ path: `/blog/${slug}`, key: `post:${slug}` })),
];

/** Every route in every locale: [{ path, key, locale, arPath, enPath }]. */
export const ALL_LOCALIZED_ROUTES = PUBLIC_SEO_ROUTES.flatMap((route) =>
  LOCALES.map((locale) => ({
    key: route.key,
    locale,
    path: withLocale(route.path, locale),
    arPath: withLocale(route.path, 'ar'),
    enPath: withLocale(route.path, 'en'),
  })),
);

export const absoluteUrl = (path) => `${SITE_ORIGIN}${path === '/' ? '/' : path}`;

/** Normalise a pathname and report its locale + base (Arabic) path. */
export function resolveLocalizedPath(pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/';
  if (clean === '/en') return { locale: 'en', basePath: '/' };
  if (clean.startsWith('/en/')) return { locale: 'en', basePath: clean.slice(3) };
  return { locale: 'ar', basePath: clean };
}

export function routeForPath(pathname) {
  const { locale, basePath } = resolveLocalizedPath(pathname);
  const route = PUBLIC_SEO_ROUTES.find((r) => r.path === basePath);
  return route ? { ...route, locale } : null;
}

/** Paths the SPA may serve (used by robots meta fallback + Vercel allow-list). */
export const PUBLIC_PATHS = ALL_LOCALIZED_ROUTES.map((r) => r.path);

/** First-segment prefixes of authenticated / auth screens served by the SPA. */
export const APP_PATH_PREFIXES = [
  'dashboard', 'inbox', 'customers', 'products', 'inventory', 'pos', 'cashier', 'sales',
  'sales-assistant', 'marketing', 'ai', 'analytics', 'owner', 'usage', 'website', 'settings',
  'orders', 'login', 'register', 'forgot-password', 'reset-password', 'verify-email',
  'accept-invitation',
];
