import { describe, expect, it } from 'vitest';
import { BLOG_POSTS } from './blog-content';
import { BLOG_SLUGS } from './public-seo-routes.mjs';
import { SOLUTIONS } from './solutions-content';

const words = (value) => String(value ?? '').split(/\s+/).filter(Boolean).length;
const bodyWords = (post, locale) => post.body.reduce((total, block) => {
  const text = block.h || block.p || (block.ul || block.ol || []);
  return total + (Array.isArray(text) ? text.reduce((n, item) => n + words(item[locale]), 0) : words(text[locale]));
}, 0);

describe('blog content', () => {
  it('has an article for every slug and no orphan articles', () => {
    expect(Object.keys(BLOG_POSTS).sort()).toEqual([...BLOG_SLUGS].sort());
  });

  it.each(BLOG_SLUGS)('%s is substantial, bilingual and honest', (slug) => {
    const post = BLOG_POSTS[slug];
    for (const locale of ['ar', 'en']) {
      expect(post.title[locale].length, `${slug} title ${locale}`).toBeGreaterThanOrEqual(30);
      expect(post.title[locale].length, `${slug} title ${locale}`).toBeLessThanOrEqual(60);
      expect(post.description[locale].length).toBeGreaterThanOrEqual(50);
      expect(post.description[locale].length).toBeLessThanOrEqual(160);
      // Thin content does not rank: every article needs real depth in both languages.
      expect(bodyWords(post, locale), `${slug} ${locale} body words`).toBeGreaterThanOrEqual(locale === 'ar' ? 900 : 1000);
    }
    expect(post.body.filter((b) => b.h).length).toBeGreaterThanOrEqual(7);
    expect(post.faq?.length, `${slug} faq`).toBeGreaterThanOrEqual(4);
    expect(SOLUTIONS[post.solution], `${slug} solution`).toBeTruthy();
    for (const related of post.related) expect(BLOG_POSTS[related], `${slug} -> ${related}`).toBeTruthy();
    // No dashes used as sentence breaks, in any visible string.
    expect(JSON.stringify(post)).not.toMatch(/[\u2013\u2014]/);
  });
});
