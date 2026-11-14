// Plain-text and Markdown renderings of the public content, for AI assistants
// and agents. Generated from the same source as the HTML pages so they cannot
// drift: llms-full.txt, llms-full-ar.txt, llms-ar.txt and one .md per page.
import { BLOG_POSTS } from '../src/lib/blog-content.js';
import { SOLUTIONS } from '../src/lib/solutions-content.js';
import { SITE_ORIGIN } from '../src/lib/public-seo-routes.mjs';

const NAME = 'FIHRIST';
const ABOUT = {
  en: 'FIHRIST is a sales operating system that connects customer conversations (WhatsApp, Messenger, Instagram, email, web chat) with products, orders, and inventory. A customer assistant can answer from store data when enabled, and a sales-analysis assistant helps read performance. Available in Arabic and English.',
  ar: 'فهرست FIHRIST نظام مبيعات يربط محادثات العملاء (واتساب وماسنجر وإنستغرام والبريد وشات الموقع) بالمنتجات والطلبات والمخزون. يمكن لمساعد العملاء الإجابة من بيانات المتجر عند تفعيله، ويساعد مساعد التحليل على قراءة الأداء. متاح بالعربية والإنجليزية.',
};

const url = (path, locale) => `${SITE_ORIGIN}${locale === 'en' ? `/en${path}` : path}`;

const blockToMarkdown = (block, locale) => {
  if (block.h) return `## ${block.h[locale]}`;
  if (block.p) return block.p[locale];
  if (block.ul) return block.ul.map((item) => `- ${item[locale]}`).join('\n');
  if (block.ol) return block.ol.map((item, i) => `${i + 1}. ${item[locale]}`).join('\n');
  return '';
};

/** One article as Markdown. */
export function postMarkdown(slug, locale) {
  const post = BLOG_POSTS[slug];
  const lines = [
    `# ${post.h1[locale]}`,
    '',
    `Source: ${url(`/blog/${slug}`, locale)}`,
    `Published: ${post.date} | Reading time: ${post.minutes} min | Publisher: ${NAME}`,
    '',
    `> ${post.lede[locale]}`,
    '',
    ...post.body.flatMap((block) => [blockToMarkdown(block, locale), '']),
  ];
  if (post.faq?.length) {
    lines.push(locale === 'ar' ? '## أسئلة شائعة' : '## Frequently asked questions', '');
    for (const item of post.faq) lines.push(`### ${item.q[locale]}`, '', item.a[locale], '');
  }
  return `${lines.join('\n').trim()}\n`;
}

/** One solution page as Markdown. */
export function solutionMarkdown(slug, locale) {
  const page = SOLUTIONS[slug];
  const lines = [
    `# ${page.h1[locale]}`,
    '',
    `Source: ${url(`/solutions/${slug}`, locale)}`,
    '',
    `> ${page.lede[locale]}`,
    '',
    locale === 'ar' ? '## ما الذي تحصل عليه' : '## What you get',
    '',
    ...(page.points || []).flatMap((point) => {
      const title = point.title?.[locale] ?? point.t?.[locale];
      const body = point.body?.[locale] ?? point.d?.[locale];
      return title || body ? [`- **${title ?? ''}**: ${body ?? ''}`.trim()] : [];
    }),
    '',
  ];
  if (page.faq?.length) {
    lines.push(locale === 'ar' ? '## أسئلة شائعة' : '## Frequently asked questions', '');
    for (const item of page.faq) lines.push(`### ${item.q[locale]}`, '', item.a[locale], '');
  }
  return `${lines.join('\n').trim()}\n`;
}

/** Every article and solution in one file, per language. */
export function buildLlmsFull(locale) {
  const header = [
    `# ${NAME}${locale === 'ar' ? ' (فهرست)' : ''}: full content`,
    '',
    `> ${ABOUT[locale]}`,
    '',
    `Website: ${SITE_ORIGIN}${locale === 'en' ? '/en' : '/'}`,
    '',
  ];
  const solutions = Object.keys(SOLUTIONS).map((slug) => solutionMarkdown(slug, locale));
  const posts = Object.keys(BLOG_POSTS).map((slug) => postMarkdown(slug, locale));
  return [...header, '---', '', ...solutions.flatMap((s) => [s, '---', '']), ...posts.flatMap((s) => [s, '---', ''])].join('\n');
}

/** Arabic index, mirroring llms.txt. */
export function buildLlmsAr() {
  const line = (path, title, desc) => `- [${title}](${url(path, 'ar')})${desc ? `: ${desc}` : ''}`;
  return [
    `# ${NAME} (فهرست)`,
    '',
    `> ${ABOUT.ar}`,
    '',
    '## الحلول',
    ...Object.entries(SOLUTIONS).map(([slug, p]) => line(`/solutions/${slug}`, p.kicker.ar, p.description.ar)),
    '',
    '## المقالات',
    ...Object.entries(BLOG_POSTS).map(([slug, p]) => line(`/blog/${slug}`, p.h1.ar, p.description.ar)),
    '',
    `النص الكامل: ${SITE_ORIGIN}/llms-full-ar.txt`,
    '',
  ].join('\n');
}
