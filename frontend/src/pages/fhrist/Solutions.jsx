import React from 'react'
import { Layers3, MessageCircle, Database, Sparkles, Inbox, Users, Target } from 'lucide-react'
import { c, tx, DetailHero, SectionIntro, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'
import { SOLUTIONS, SOLUTIONS_INDEX } from '@/lib/solutions-content'
import { localizePath } from '@/lib/locale-paths'

const ICONS = {
  'whatsapp-sales-system': MessageCircle,
  'inventory-management-system': Database,
  'ai-sales-assistant': Sparkles,
  'unified-inbox': Inbox,
  'pos-cashier-system': Target,
  'sales-crm-for-stores': Users,
  'order-management-system': Layers3,
}

/** /solutions : an index of every keyword landing page. */
export function SolutionsIndex({ locale }) {
  const items = Object.entries(SOLUTIONS).map(([slug, page]) => ({
    icon: ICONS[slug] || Layers3,
    title: page.kicker,
    body: page.description,
    href: localizePath(`/solutions/${slug}`, locale),
  }))
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الحلول', 'Solutions')}
        title={SOLUTIONS_INDEX.h1}
        body={SOLUTIONS_INDEX.lede}
        icon={Layers3}
        ctaHref={localizePath('/contact-sales', locale)}
        ctaLabel={c('تواصل مع المبيعات', 'Contact sales')}
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('اختر حلًا', 'Pick a solution'), locale)}
            title={tx(c('ابدأ من الجزء الأهم لمتجرك.', 'Start with the part that matters most to your store.'), locale)}
            body={tx(c('كل حل يعمل على نفس بيانات العميل والمنتج والطلب.', 'Every solution runs on the same customer, product, and order data.'), locale)}
          />
          <FeatureGrid items={items} locale={locale} />
        </div>
      </section>
    </>
  )
}

/** /solutions/:slug : one keyword landing page. */
export default function SolutionPage({ slug, locale }) {
  const page = SOLUTIONS[slug]
  if (!page) return null
  const Icon = ICONS[slug] || Layers3
  const others = Object.entries(SOLUTIONS)
    .filter(([key]) => key !== slug)
    .slice(0, 3)
    .map(([key, p]) => ({
      icon: ICONS[key] || Layers3,
      title: p.kicker,
      body: p.description,
      href: localizePath(`/solutions/${key}`, locale),
    }))
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={page.kicker}
        title={page.h1}
        body={page.lede}
        icon={Icon}
        ctaHref={localizePath('/contact-sales', locale)}
        ctaLabel={c('تواصل مع المبيعات', 'Contact sales')}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('ماذا ستحصل عليه', 'What you get'), locale)}
            title={tx(page.h1, locale)}
            body={tx(page.lede, locale)}
          />
          <DetailPoints points={page.points} locale={locale} />
        </div>
      </section>
      <section className="section section-faq">
        <div className="container faq-wrap">
          <SectionIntro
            kicker={tx(c('أسئلة شائعة', 'FAQ'), locale)}
            title={tx(c('قبل أن تسأل.', 'Before you ask.'), locale)}
          />
          {page.faq.map((item) => (
            <details className="faq-item" key={item.q.en}>
              <summary><span>{tx(item.q, locale)}</span></summary>
              <p>{tx(item.a, locale)}</p>
            </details>
          ))}
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('حلول أخرى', 'More solutions'), locale)}
            title={tx(c('اكتشف ما يكمّل هذا الحل.', 'See what complements this solution.'), locale)}
          />
          <FeatureGrid items={others} locale={locale} />
        </div>
      </section>
    </>
  )
}
