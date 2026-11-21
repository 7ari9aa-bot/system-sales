import assert from 'node:assert/strict';
import { buildLlmsAr, buildLlmsFull, postMarkdown, solutionMarkdown } from './ai-text.mjs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import {
  ALL_LOCALIZED_ROUTES,
  LIVE_COUNTRY_SLUGS,
  PUBLIC_PATHS,
  PUBLIC_SEO_ROUTES,
  SITE_ORIGIN,
  absoluteUrl,
} from '../src/lib/public-seo-routes.mjs';
import { localizeHtmlString } from '../src/lib/locale-paths.js';
import { buildSchemas, buildLlmsTxt, buildSitemap } from './seo-helpers.mjs';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distRoot = path.join(frontendRoot, 'dist');
const indexPath = path.join(distRoot, 'index.html');
const origin = SITE_ORIGIN;
const startMarker = '<!-- seo-prerender-start -->';
const endMarker = '<!-- seo-prerender-end -->';

function escapeHtml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function setMeta(html, kind, name, value) {
  const pattern = new RegExp(`<meta\\s+${kind}="${escapeRegExp(name)}"\\s+content="[^"]*"\\s*\\/?>(?![^<]*>)`, 'i');
  assert.match(html, pattern, `Missing ${kind} metadata: ${name}`);
  return html.replace(pattern, () => `<meta ${kind}="${name}" content="${escapeAttribute(value)}" />`);
}

function replaceRoot(html, markup) {
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, 'Missing prerender start marker in index.html');
  assert.notEqual(end, -1, 'Missing prerender end marker in index.html');
  return `${html.slice(0, start + startMarker.length)}${markup}${html.slice(end)}`;
}

function hreflangTags(route) {
  const hasMarkdown = route.key?.startsWith('post:') || route.key?.startsWith('solution:');
  const aiLinks = [
    ...(hasMarkdown ? [`<link rel="alternate" type="text/markdown" href="${escapeAttribute(absoluteUrl(`${route.path}.md`))}" />`] : []),
    `<link rel="alternate" type="text/plain" href="${escapeAttribute(absoluteUrl(route.locale === 'en' ? '/llms-full.txt' : '/llms-full-ar.txt'))}" title="llms-full" />`,
  ];

  if (route.isSelector) {
    return [
      `<link rel="alternate" hreflang="x-default" href="${escapeAttribute(absoluteUrl('/'))}" />`,
      ...aiLinks,
    ].join('\n    ');
  }

  const cleanBase = route.basePath === '/' ? '' : (route.basePath || '');
  const tags = [];
  for (const c of LIVE_COUNTRY_SLUGS) {
    tags.push(`<link rel="alternate" hreflang="ar-${c.toUpperCase()}" href="${escapeAttribute(absoluteUrl(`/${c}/ar${cleanBase}`))}" />`);
    tags.push(`<link rel="alternate" hreflang="en-${c.toUpperCase()}" href="${escapeAttribute(absoluteUrl(`/${c}/en${cleanBase}`))}" />`);
  }
  tags.push(`<link rel="alternate" hreflang="x-default" href="${escapeAttribute(absoluteUrl('/'))}" />`);

  return [...tags, ...aiLinks].join('\n    ');
}

function updateDocument(template, route, markup, title, description, schemas, publicPaths) {
  const canonical = absoluteUrl(route.path);
  const isEn = route.locale === 'en';
  let html = template;
  html = html.replace(/<html[^>]*>/i, `<html lang="${route.locale}" dir="${isEn ? 'ltr' : 'rtl'}">`);
  html = html.replace(/<title>[\s\S]*?<\/title>/i, () => `<title>${escapeHtml(title)}</title>`);
  html = setMeta(html, 'name', 'description', description);
  html = setMeta(html, 'name', 'seo-public-paths', publicPaths.join(','));
  html = html.replace(/<link\s+rel="canonical"\s+href="[^"]*"\s*\/>/i, () => `<link rel="canonical" href="${escapeAttribute(canonical)}" />\n    ${hreflangTags(route)}`);
  html = setMeta(html, 'property', 'og:title', title);
  html = setMeta(html, 'property', 'og:description', description);
  html = setMeta(html, 'property', 'og:url', canonical);
  html = setMeta(html, 'property', 'og:locale', isEn ? 'en_US' : 'ar_EG');
  html = setMeta(html, 'name', 'twitter:title', title);
  html = setMeta(html, 'name', 'twitter:description', description);
  const jsonLd = schemas.map((schema) => `<script type="application/ld+json">${JSON.stringify(schema).replaceAll('<', '\\u003c')}</script>`).join('\n    ');
  html = html.replace(/<script\s+type="application\/ld\+json">[\s\S]*?<\/script>/i, () => jsonLd);
  html = replaceRoot(html, localizeHtmlString(markup, route.locale, route.country));
  return html;
}

async function main() {
  const template = await readFile(indexPath, 'utf8');
  assert.ok(template.includes(startMarker) && template.includes(endMarker), 'Vite output lost the prerender markers');

  globalThis.window = {
    location: { pathname: '/', search: '', hash: '', origin, href: `${origin}/` },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
  };

  const vite = await createServer({
    root: frontendRoot,
    configFile: path.join(frontendRoot, 'vite.config.js'),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'error',
  });

  const renderedHeadings = new Set();
  const generated = [];
  try {
    const { default: Fihrist, metaFor } = await vite.ssrLoadModule('/src/pages/Fihrist.jsx');

    for (const route of ALL_LOCALIZED_ROUTES) {
      globalThis.window.location.pathname = route.path;
      globalThis.window.location.href = absoluteUrl(route.path);
      const markup = renderToStaticMarkup(React.createElement(Fihrist));
      const title = metaFor(route.key, 'title')?.[route.locale];
      const description = metaFor(route.key, 'description')?.[route.locale];
      assert.ok(title && description, `Missing ${route.locale} SEO copy for ${route.path}`);
      assert.ok(title.length >= 30 && title.length <= 60, `Title length must be 30-60 characters (${route.locale}): ${route.path} (${title.length})`);
      assert.ok(description.length >= 50 && description.length <= 160, `Description length must be 50-160 characters (${route.locale}): ${route.path} (${description.length})`);
      assert.match(markup, /<h1\b/, `Prerendered page has no H1: ${route.path}`);
      const heading = markup.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/)?.[1] ?? '';
      assert.ok(heading, `Could not extract H1 for ${route.path}`);
      renderedHeadings.add(`${route.country || 'root'}:${route.locale}:${heading}`);

      const schemas = buildSchemas(route, title, description, markup);
      const html = updateDocument(template, route, markup, title, description, schemas, PUBLIC_PATHS);
      const canonical = absoluteUrl(route.path);
      assert.ok(html.includes(`<title>${escapeHtml(title)}</title>`), `Title is not route-specific: ${route.path}`);
      assert.ok(html.includes(`rel="canonical" href="${canonical}"`), `Canonical is not route-specific: ${route.path}`);
      assert.ok(html.includes(escapeAttribute(description)), `Description is missing: ${route.path}`);
      assert.ok(html.includes('hreflang="x-default"'), `hreflang is missing: ${route.path}`);
      assert.ok(!html.includes('/src/main.jsx'), `Unbuilt development entry remains in ${route.path}`);
      // Every internal public link stays inside this page's own country and language.
      const ownPrefix = `/${route.country}/${route.locale}`;
      const strays = [...html.matchAll(/<a\b[^>]*?\shref="(\/[^"]*)"/g)]
        .map((m) => m[1])
        .filter((href) => /^\/(product|pricing|conversations|context|assistant|automation|security|privacy|terms|data-deletion|contact-sales|support|solutions|blog|en)(\/|$|[?#])/.test(href));
      assert.deepEqual(strays, [], `${route.path} links outside ${ownPrefix}`);

      const outputPath = route.path === '/'
        ? indexPath
        : path.join(distRoot, route.path.slice(1), 'index.html');
      await mkdir(path.dirname(outputPath), { recursive: true });
      await writeFile(outputPath, html);
      generated.push(route.path);
    }

    assert.equal(renderedHeadings.size, ALL_LOCALIZED_ROUTES.length, 'Public pages should have distinct initial H1 content');

    const lastmod = new Date().toISOString().slice(0, 10);
    await writeFile(path.join(distRoot, 'sitemap.xml'), buildSitemap(ALL_LOCALIZED_ROUTES, lastmod));
    await writeFile(path.join(distRoot, 'llms.txt'), buildLlmsTxt(PUBLIC_SEO_ROUTES));
    await writeFile(path.join(distRoot, 'llms-ar.txt'), buildLlmsAr());
    await writeFile(path.join(distRoot, 'llms-full.txt'), buildLlmsFull('en'));
    await writeFile(path.join(distRoot, 'llms-full-ar.txt'), buildLlmsFull('ar'));
    // A clean Markdown twin of every article and solution (e.g. /blog/<slug>.md).
    for (const route of ALL_LOCALIZED_ROUTES) {
      const kind = route.key?.startsWith('post:') ? postMarkdown : route.key?.startsWith('solution:') ? solutionMarkdown : null;
      if (!kind) continue;
      const base = route.arPath;
      const slug = base.split('/').pop();
      const file = path.join(distRoot, `${route.path.slice(1)}.md`);
      await mkdir(path.dirname(file), { recursive: true });
      await writeFile(file, kind(slug, route.locale));
    }
    console.log(`Prerendered ${generated.length} public FIHRIST pages (ar + en) with route-specific HTML, hreflang and schema.`);
  } finally {
    await vite.close();
    delete globalThis.window;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
