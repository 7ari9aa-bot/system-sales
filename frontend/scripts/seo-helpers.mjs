import { SITE_ORIGIN, absoluteUrl } from '../src/lib/public-seo-routes.mjs';
import { SOLUTIONS } from '../src/lib/solutions-content.js';
import { BLOG_POSTS } from '../src/lib/blog-content.js';

const NAME = 'FIHRIST';

const BREADCRUMB_LABEL = {
  product: { ar: 'المنصة', en: 'Platform' },
  conversations: { ar: 'المحادثات', en: 'Conversations' },
  context: { ar: 'السياق', en: 'Context' },
  assistant: { ar: 'المساعد', en: 'Assistant' },
  automation: { ar: 'الأتمتة', en: 'Automation' },
  pricing: { ar: 'الأسعار', en: 'Pricing' },
  security: { ar: 'الأمان', en: 'Security' },
  privacy: { ar: 'الخصوصية', en: 'Privacy' },
  terms: { ar: 'الشروط', en: 'Terms' },
  'contact-sales': { ar: 'تواصل مع المبيعات', en: 'Contact sales' },
  support: { ar: 'الدعم', en: 'Support' },
  solutions: { ar: 'الحلول', en: 'Solutions' },
  blog: { ar: 'المدونة', en: 'Blog' },
};

const ORG_DESCRIPTION = {
  ar: 'FIHRIST نظام تشغيل مبيعات يربط محادثات العملاء بالمنتجات والطلبات والمخزون.',
  en: 'FIHRIST is a sales operating system that connects customer conversations with products, orders, and inventory.',
};

const organization = () => ({
  '@type': 'Organization',
  '@id': `${SITE_ORIGIN}/#organization`,
  name: NAME,
  url: `${SITE_ORIGIN}/`,
  logo: `${SITE_ORIGIN}/fihrist-mark.svg`,
  description: ORG_DESCRIPTION.en,
});

const website = () => ({
  '@type': 'WebSite',
  '@id': `${SITE_ORIGIN}/#website`,
  name: NAME,
  url: `${SITE_ORIGIN}/`,
  inLanguage: ['ar', 'en'],
  publisher: { '@id': `${SITE_ORIGIN}/#organization` },
});

function breadcrumbs(route) {
  const baseKey = route.key.startsWith('solution:') ? 'solutions' : route.key;
  const isPost = route.key.startsWith('post:');
  const homePath = route.locale === 'en' ? '/en' : '/';
  const items = [{ name: NAME, item: absoluteUrl(homePath) }];
  if (route.key !== 'home') {
    if (route.key.startsWith('solution:')) {
      const solutionsPath = route.locale === 'en' ? '/en/solutions' : '/solutions';
      items.push({ name: BREADCRUMB_LABEL.solutions[route.locale], item: absoluteUrl(solutionsPath) });
    }
    if (isPost) {
      const blogPath = route.locale === 'en' ? '/en/blog' : '/blog';
      items.push({ name: BREADCRUMB_LABEL.blog[route.locale], item: absoluteUrl(blogPath) });
    }
    const label = isPost
      ? BLOG_POSTS[route.key.slice('post:'.length)].h1[route.locale]
      : route.key.startsWith('solution:')
      ? SOLUTIONS[route.key.slice('solution:'.length)].kicker[route.locale]
      : BREADCRUMB_LABEL[baseKey]?.[route.locale];
    if (label) items.push({ name: label, item: absoluteUrl(route.path) });
  }
  return {
    '@type': 'BreadcrumbList',
    itemListElement: items.map((entry, index) => ({ '@type': 'ListItem', position: index + 1, name: entry.name, item: entry.item })),
  };
}

function faqSchema(route) {
  let page = null;
  if (route.key.startsWith('solution:')) page = SOLUTIONS[route.key.slice('solution:'.length)];
  if (route.key.startsWith('post:')) page = BLOG_POSTS[route.key.slice('post:'.length)];
  if (!page) return null;
  if (!page?.faq?.length) return null;
  return {
    '@type': 'FAQPage',
    mainEntity: page.faq.map((entry) => ({
      '@type': 'Question',
      name: entry.q[route.locale],
      acceptedAnswer: { '@type': 'Answer', text: entry.a[route.locale] },
    })),
  };
}

/** One JSON-LD block per entry; every block carries its own @context. */
export function buildSchemas(route, title, description) {
  const canonical = absoluteUrl(route.path);
  const page = {
    '@type': 'WebPage',
    '@id': `${canonical}#webpage`,
    name: title,
    description,
    url: canonical,
    inLanguage: route.locale,
    isPartOf: { '@id': `${SITE_ORIGIN}/#website` },
  };
  if (route.key === 'home' || route.key === 'product') {
    page.mainEntity = {
      '@type': 'SoftwareApplication',
      name: NAME,
      url: `${SITE_ORIGIN}/`,
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      inLanguage: ['ar', 'en'],
      description,
    };
  }
  const blocks = [page, breadcrumbs(route)];
  if (route.key.startsWith('post:')) {
    const post = BLOG_POSTS[route.key.slice('post:'.length)];
    blocks.push({
      '@type': 'Article',
      headline: post.h1[route.locale],
      description,
      inLanguage: route.locale,
      datePublished: post.date,
      dateModified: post.date,
      mainEntityOfPage: canonical,
      author: { '@id': `${SITE_ORIGIN}/#organization` },
      publisher: { '@id': `${SITE_ORIGIN}/#organization` },
    });
  }
  if (route.key === 'home') blocks.unshift(organization(), website());
  const faq = faqSchema(route);
  if (faq) blocks.push(faq);
  return blocks.map((block) => ({ '@context': 'https://schema.org', ...block }));
}

const escapeXml = (value) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

/** Sitemap with one <url> per localized page and xhtml alternates (hreflang). */
export function buildSitemap(routes, lastmod) {
  const urls = routes.map((route) => {
    const ar = escapeXml(absoluteUrl(route.arPath));
    const en = escapeXml(absoluteUrl(route.enPath));
    return [
      '  <url>',
      `    <loc>${escapeXml(absoluteUrl(route.path))}</loc>`,
      `    <lastmod>${lastmod}</lastmod>`,
      `    <xhtml:link rel="alternate" hreflang="ar" href="${ar}" />`,
      `    <xhtml:link rel="alternate" hreflang="en" href="${en}" />`,
      `    <xhtml:link rel="alternate" hreflang="x-default" href="${ar}" />`,
      '  </url>',
    ].join('\n');
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urls.join('\n')}\n</urlset>\n`;
}

/** llms.txt: a short, honest, machine-readable summary for AI assistants. */
export function buildLlmsTxt(routes) {
  const label = (route) => {
    if (route.key === 'home') return 'Home';
    if (route.key === 'solutions') return 'Solutions';
    if (route.key === 'blog') return 'Blog';
    if (route.key.startsWith('post:')) return BLOG_POSTS[route.key.slice('post:'.length)].h1.en;
    if (route.key.startsWith('solution:')) return SOLUTIONS[route.key.slice('solution:'.length)].kicker.en;
    return BREADCRUMB_LABEL[route.key]?.en ?? route.key;
  };
  const line = (route) => {
    const desc = route.key.startsWith('solution:') ? SOLUTIONS[route.key.slice('solution:'.length)].description.en
      : route.key.startsWith('post:') ? BLOG_POSTS[route.key.slice('post:'.length)].description.en : '';
    return `- [${label(route)}](${absoluteUrl(route.path)})${desc ? `: ${desc}` : ''}`;
  };
  const core = routes.filter((r) => !r.key.startsWith('solution') && !r.key.startsWith('post:') && !['privacy', 'terms'].includes(r.key));
  const posts = routes.filter((r) => r.key.startsWith('post:'));
  const solutions = routes.filter((r) => r.key.startsWith('solution:'));
  const english = (route) => ({ ...route, path: route.path === '/' ? '/en' : `/en${route.path}` });
  return [
    `# ${NAME}`,
    '',
    `> ${ORG_DESCRIPTION.en}`,
    '',
    `${NAME} brings WhatsApp, Messenger, Instagram, email, and web chat into one inbox and links each conversation to the customer, product, order, and stock. A customer assistant can answer from store data when enabled, and a sales-analysis assistant helps read performance. The site is available in Arabic (default) and English (/en).`,
    '',
    '## Product',
    ...core.map((r) => line(english(r))),
    '',
    '## Solutions',
    ...solutions.map((r) => line(english(r))),
    '',
    '## Articles',
    ...posts.map((r) => line(english(r))),
    '',
    '## Full text for AI assistants',
    `- [Full content in English](${SITE_ORIGIN}/llms-full.txt): every article and solution as plain text.`,
    `- [Full content in Arabic](${SITE_ORIGIN}/llms-full-ar.txt): the same content in Arabic, the primary language.`,
    `- [Arabic index](${SITE_ORIGIN}/llms-ar.txt)`,
    '- Every article and solution page also has a Markdown version: add .md to its URL.',
    '',
    '## Legal',
    `- [Privacy](${absoluteUrl('/en/privacy')})`,
    `- [Terms](${absoluteUrl('/en/terms')})`,
    '',
  ].join('\n');
}
