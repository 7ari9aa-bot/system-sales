import React from 'react'
import { BookOpen } from 'lucide-react'
import { c, tx, DetailHero, SectionIntro, FeatureGrid, Button } from '@/components/fihrist/Shared'
import { BLOG_POSTS, BLOG_INDEX } from '@/lib/blog-content'
import { SOLUTIONS } from '@/lib/solutions-content'
import { localizePath } from '@/lib/locale-paths'
import { useCountry } from '@/lib/CountryContext'

const cardFor = (slug, post, locale, country) => ({
  icon: BookOpen,
  title: post.h1,
  body: post.description,
  href: localizePath(`/blog/${slug}`, locale, country),
})

/** /blog : the article index. */
export function BlogIndex({ locale }) {
  const { country } = useCountry()
  const items = Object.entries(BLOG_POSTS).map(([slug, post]) => cardFor(slug, post, locale, country))
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المدونة', 'Blog')}
        title={BLOG_INDEX.h1}
        body={BLOG_INDEX.lede}
        icon={BookOpen}
        ctaHref={localizePath('/solutions', locale, country)}
        ctaLabel={c('استعرض الحلول', 'Explore solutions')}
      />
      <section className="section section-features">
        <div className="container">
          <FeatureGrid items={items} locale={locale} />
        </div>
      </section>
    </>
  )
}

const renderBlock = (block, index, locale) => {
  if (block.h) return <h2 key={index} className="post-h2">{tx(block.h, locale)}</h2>
  if (block.p) return <p key={index} className="post-p">{tx(block.p, locale)}</p>
  const List = block.ol ? 'ol' : 'ul'
  const items = block.ol || block.ul
  return <List key={index} className="post-list">{items.map((item) => <li key={item.en}>{tx(item, locale)}</li>)}</List>
}

/** /blog/:slug : one article. */
export default function BlogPost({ slug, locale }) {
  const { country } = useCountry()
  const post = BLOG_POSTS[slug]
  if (!post) return null
  const related = (post.related || []).filter((key) => BLOG_POSTS[key]).map((key) => cardFor(key, BLOG_POSTS[key], locale, country))
  const solution = SOLUTIONS[post.solution]
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={tx(c(`مقال · ${post.minutes} دقائق قراءة`, `Article · ${post.minutes} min read`), locale)}
        title={post.h1}
        body={post.lede}
        icon={BookOpen}
        ctaHref={localizePath('/contact-sales', locale, country)}
        ctaLabel={c('تواصل مع المبيعات', 'Contact sales')}
      />
      <article className="section">
        <div className="container post-body">
          {post.body.map((block, index) => renderBlock(block, index, locale))}
          {post.faq?.length > 0 && (
            <section className="post-faq">
              <h2 className="post-h2">{tx(c('أسئلة شائعة', 'Frequently asked questions'), locale)}</h2>
              {post.faq.map((item) => (
                <details className="faq-item" key={item.q.en}>
                  <summary><span>{tx(item.q, locale)}</span></summary>
                  <p>{tx(item.a, locale)}</p>
                </details>
              ))}
            </section>
          )}
          {solution && (
            <p className="post-cta">
              <Button href={localizePath(`/solutions/${post.solution}`, locale, country)} kind="secondary">
                {tx(solution.kicker, locale)}
              </Button>
            </p>
          )}
        </div>
      </article>
      {related.length > 0 && (
        <section className="section section-features">
          <div className="container">
            <SectionIntro kicker={tx(c('اقرأ أيضًا', 'Read next'), locale)} title={tx(c('مقالات ذات صلة.', 'Related articles.'), locale)} />
            <FeatureGrid items={related} locale={locale} />
          </div>
        </section>
      )}
    </>
  )
}
