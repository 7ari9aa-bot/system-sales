// Blog content entry point. Articles live in ./blog/posts-*.js.
// Titles stay 30-60 characters and descriptions 50-160 (the prerender asserts this).
import { POSTS_1 } from './blog/posts-1.js';
import { POSTS_2 } from './blog/posts-2.js';
import { POSTS_3 } from './blog/posts-3.js';
import { POSTS_4 } from './blog/posts-4.js';
import { POSTS_5 } from './blog/posts-5.js';

const c = (ar, en) => ({ ar, en });

export const BLOG_POSTS = { ...POSTS_1, ...POSTS_2, ...POSTS_3, ...POSTS_4, ...POSTS_5 };

export const BLOG_INDEX = {
  title: c('مدونة FIHRIST: أدلة عملية لأصحاب المتاجر', 'FIHRIST Blog: Practical Guides for Store Owners'),
  description: c(
    'أدلة عملية لأصحاب المتاجر: البيع على واتساب، متابعة المخزون، الرد على العملاء، والمتابعة، وقراءة تقارير المبيعات.',
    'Practical guides for store owners: selling on WhatsApp, tracking inventory, replying to customers, following up, and reading sales reports.',
  ),
  h1: c('أدلة عملية لتبيع بشكل أكثر انتظامًا.', 'Practical guides to sell in a more organized way.'),
  lede: c(
    'مقالات قصيرة بخطوات تطبّقها اليوم، مكتوبة لأصحاب المتاجر الذين يبيعون عبر المحادثات.',
    'Short articles with steps you can apply today, written for store owners who sell through conversations.',
  ),
};
