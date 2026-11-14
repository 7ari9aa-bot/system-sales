import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildLlmsAr, buildLlmsFull, postMarkdown, solutionMarkdown } from '../../scripts/ai-text.mjs';
import { BLOG_POSTS } from './blog-content';
import { SOLUTIONS } from './solutions-content';

const robots = readFileSync(new URL('../../public/robots.txt', import.meta.url), 'utf8');

describe('robots.txt for AI crawlers', () => {
  it.each(['GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'PerplexityBot', 'Google-Extended'])(
    'names %s and allows public content',
    (bot) => {
      const group = robots.split(/\n\s*\n/).find((g) => g.includes(`User-agent: ${bot}`));
      expect(group, bot).toBeTruthy();
      expect(group).toMatch(/^Allow: \/$/m);
      expect(group).not.toMatch(/^Disallow: \/$/m);
    },
  );

  it('keeps private screens closed to every crawler and lists the sitemap', () => {
    for (const group of robots.split(/\n\s*\n/).filter((g) => g.includes('User-agent'))) {
      for (const path of ['/dashboard', '/inbox', '/api/', '/settings']) expect(group).toContain(`Disallow: ${path}`);
    }
    expect(robots).toContain('Sitemap: https://fihrist.world/sitemap.xml');
  });
});

describe('AI text outputs', () => {
  it.each(['ar', 'en'])('llms-full (%s) contains every article and solution', (locale) => {
    const full = buildLlmsFull(locale);
    for (const post of Object.values(BLOG_POSTS)) expect(full).toContain(post.h1[locale]);
    for (const page of Object.values(SOLUTIONS)) expect(full).toContain(page.h1[locale]);
    expect(full).not.toMatch(/[\u2013\u2014]/);
  });

  it('every article renders to Markdown with its source URL, headings and FAQ', () => {
    for (const slug of Object.keys(BLOG_POSTS)) {
      for (const locale of ['ar', 'en']) {
        const md = postMarkdown(slug, locale);
        expect(md.startsWith('# ')).toBe(true);
        expect(md).toContain(`https://fihrist.world${locale === 'en' ? '/en' : ''}/blog/${slug}`);
        expect((md.match(/^## /gm) || []).length).toBeGreaterThanOrEqual(7);
        expect((md.match(/^### /gm) || []).length).toBeGreaterThanOrEqual(4);
      }
    }
  });

  it('solution Markdown has real point text (no "undefined")', () => {
    for (const slug of Object.keys(SOLUTIONS)) {
      const md = solutionMarkdown(slug, 'en');
      expect(md).not.toContain('undefined');
      expect((md.match(/^- \*\*/gm) || []).length).toBeGreaterThanOrEqual(3);
    }
  });

  it('Arabic index links to the Arabic articles', () => {
    const index = buildLlmsAr();
    for (const slug of Object.keys(BLOG_POSTS)) expect(index).toContain(`https://fihrist.world/blog/${slug}`);
  });
});
