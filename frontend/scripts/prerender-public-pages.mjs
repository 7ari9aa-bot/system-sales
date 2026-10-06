import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { PUBLIC_SEO_ROUTES } from '../src/lib/public-seo-routes.mjs';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distRoot = path.join(frontendRoot, 'dist');
const indexPath = path.join(distRoot, 'index.html');
const origin = 'https://fihrist.world';
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
  return html.replace(pattern, `<meta ${kind}="${name}" content="${escapeAttribute(value)}" />`);
}

function replaceRoot(html, markup) {
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, 'Missing prerender start marker in index.html');
  assert.notEqual(end, -1, 'Missing prerender end marker in index.html');
  return `${html.slice(0, start + startMarker.length)}${markup}${html.slice(end)}`;
}

function updateDocument(template, route, markup, title, description, schema, publicPaths) {
  const canonical = `${origin}${route.path === '/' ? '/' : route.path}`;
  let html = template;
  html = html.replace(/<title>[\s\S]*?<\/title>/i, `<title>${escapeHtml(title)}</title>`);
  html = setMeta(html, 'name', 'description', description);
  html = setMeta(html, 'name', 'seo-public-paths', publicPaths.join(','));
  html = html.replace(/<link\s+rel="canonical"\s+href="[^"]*"\s*\/>/i, `<link rel="canonical" href="${escapeAttribute(canonical)}" />`);
  html = setMeta(html, 'property', 'og:title', title);
  html = setMeta(html, 'property', 'og:description', description);
  html = setMeta(html, 'property', 'og:url', canonical);
  html = setMeta(html, 'name', 'twitter:title', title);
  html = setMeta(html, 'name', 'twitter:description', description);
  const jsonLd = JSON.stringify(schema).replaceAll('<', '\\u003c');
  html = html.replace(/<script\s+type="application\/ld\+json">[\s\S]*?<\/script>/i, `<script type="application/ld+json">${jsonLd}</script>`);
  html = replaceRoot(html, markup);
  return html;
}

function buildSchema(route, title, description) {
  const canonical = `${origin}${route.path === '/' ? '/' : route.path}`;
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: title,
    description,
    url: canonical,
    inLanguage: 'ar',
    isPartOf: { '@type': 'WebSite', name: 'FIHRIST', url: `${origin}/` },
  };
  if (route.key === 'home' || route.key === 'product') {
    schema.mainEntity = {
      '@type': 'SoftwareApplication',
      name: 'FIHRIST',
      url: `${origin}/`,
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      inLanguage: ['ar', 'en'],
      description,
    };
  }
  return schema;
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
  try {
    const { default: Fihrist, pageMeta, pageDescription } = await vite.ssrLoadModule('/src/pages/Fihrist.jsx');
    const publicPaths = PUBLIC_SEO_ROUTES.map(({ path: routePath }) => routePath);
    const sitemap = await readFile(path.join(frontendRoot, 'public/sitemap.xml'), 'utf8');
    const sitemapUrls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
    const expectedSitemapUrls = PUBLIC_SEO_ROUTES.map(({ path: routePath }) => `${origin}${routePath === '/' ? '/' : routePath}`);
    assert.deepEqual(sitemapUrls, expectedSitemapUrls, 'sitemap.xml must list every public SEO route exactly once and in route order');

    for (const route of PUBLIC_SEO_ROUTES) {
      globalThis.window.location.pathname = route.path;
      globalThis.window.location.href = `${origin}${route.path === '/' ? '/' : route.path}`;
      const markup = renderToStaticMarkup(React.createElement(Fihrist));
      const title = pageMeta[route.key]?.ar;
      const description = pageDescription[route.key]?.ar;
      assert.ok(title && description, `Missing Arabic SEO copy for ${route.path}`);
      for (const locale of ['ar', 'en']) {
        const localizedTitle = pageMeta[route.key]?.[locale];
        const localizedDescription = pageDescription[route.key]?.[locale];
        assert.ok(localizedTitle?.length >= 30 && localizedTitle.length <= 60, `Title length must be 30–60 characters (${locale}): ${route.path}`);
        assert.ok(localizedDescription?.length >= 50 && localizedDescription.length <= 160, `Description length must be 50–160 characters (${locale}): ${route.path}`);
      }
      assert.match(markup, /<h1\b/, `Prerendered page has no H1: ${route.path}`);
      const heading = markup.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/)?.[1] ?? '';
      assert.ok(heading, `Could not extract H1 for ${route.path}`);
      renderedHeadings.add(heading);

      const schema = buildSchema(route, title, description);
      const html = updateDocument(template, route, markup, title, description, schema, publicPaths);
      const canonical = `${origin}${route.path === '/' ? '/' : route.path}`;
      assert.ok(html.includes(`<title>${escapeHtml(title)}</title>`), `Title is not route-specific: ${route.path}`);
      assert.ok(html.includes(`href="${canonical}"`), `Canonical is not route-specific: ${route.path}`);
      assert.ok(html.includes(escapeAttribute(description)), `Description is missing: ${route.path}`);
      assert.ok(!html.includes('/src/main.jsx'), `Unbuilt development entry remains in ${route.path}`);

      const outputPath = route.path === '/'
        ? indexPath
        : path.join(distRoot, route.path.slice(1), 'index.html');
      await mkdir(path.dirname(outputPath), { recursive: true });
      await writeFile(outputPath, html);
    }

    assert.equal(renderedHeadings.size, PUBLIC_SEO_ROUTES.length, 'Public pages should have distinct initial H1 content');
    console.log(`Prerendered ${PUBLIC_SEO_ROUTES.length} public FIHRIST pages with route-specific HTML and metadata.`);
  } finally {
    await vite.close();
    delete globalThis.window;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
