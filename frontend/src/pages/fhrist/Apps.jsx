import React from 'react'
import { Layers3, Target, Database, Inbox, Users, Sparkles, MessageCircle } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'
import { APPS } from '@/lib/apps-content'
import { localizePath } from '@/lib/locale-paths'
import { useCountry } from '@/lib/CountryContext'

/** SectionIntro renders its strings as-is (it does not localize), so resolve here. */
const L = (value, locale) => (value && typeof value === 'object' ? value[locale] || value.ar : value)

const ICONS = {
  'retail-core': Target,
  'retail-purchasing': Layers3,
  'retail-warehouse': Database,
  'inventory-advanced': Inbox,
  'customer-engagement': Users,
  'ai-support': Sparkles,
  'business-intelligence': MessageCircle,
}

/** /apps : every application, what it does, and how it connects to the others. */
export function AppsIndex({ locale }) {
  const { country } = useCountry()
  const items = Object.entries(APPS).map(([slug, page]) => ({
    icon: ICONS[slug] || Layers3,
    title: page.kicker,
    body: page.description,
    href: localizePath(`/apps/${slug}`, locale, country),
  }))
  return (
    <>
      <DetailHero
        locale={locale}
        icon={Layers3}
        kicker={c('التطبيقات', 'Applications')}
        title={c('محلك بيتبني من تطبيقات', 'Your store is built from applications')}
        body={c(
          'كل تطبيق بيضيف وظيفة واحدة واضحة، وباقتك هي اللي تحدد المتاح لك. تقدر تبدأ بالأساسي وتضيف اللي شغلك محتاجه لما يكبر.',
          'Each application adds one clear capability, and your plan decides what is available. Start with the core and add what your business needs as it grows.'
        )}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            locale={locale}
            kicker={L(c('سبعة تطبيقات', 'Seven applications'), locale)}
            title={L(c('اللي متاح دلوقتي', 'Available today'), locale)}
          />
          <FeatureGrid locale={locale} items={items} />
        </div>
      </section>
      <section className="section section-alt">
        <div className="container">
          <SectionIntro
            locale={locale}
            kicker={L(c('مش قائمة تسويقية', 'Not a marketing list'), locale)}
            title={L(c('كل تطبيق وراه كود بيسأل عنه', 'Every application is enforced in the API'), locale)}
            body={L(c(
              'الحقوق بتتحدد من الاشتراك، والتثبيت من إعدادات النشاط، والصلاحية من دور الموظف. لو تطبيق مش متاح لحسابك، الخادم نفسه بيرفض الطلب مش بس بيخفي القائمة.',
              'Rights come from the subscription, installation from the business settings, and permission from the staff role. When an application is not available to your account, the server refuses the request instead of only hiding a menu.'
            ), locale)}
          />
        </div>
      </section>
    </>
  )
}

/** /apps/:slug : one application. */
export default function AppPage({ slug, locale }) {
  const page = APPS[slug]
  if (!page) return null
  const others = Object.entries(APPS)
    .filter(([key]) => key !== slug)
    .map(([key, entry]) => ({
      icon: ICONS[key] || Layers3,
      title: entry.kicker,
      body: entry.description,
      href: localizePath(`/apps/${key}`, locale),
    }))
  return (
    <>
      <DetailHero
        locale={locale}
        icon={ICONS[slug] || Layers3}
        kicker={page.kicker}
        title={page.title}
        body={page.description}
      />
      <section className="section">
        <div className="container">
          <DetailPoints
            locale={locale}
            points={(page.points[locale] || page.points.ar).map((text) => ({ title: text, body: '' }))}
          />
        </div>
      </section>
      <section className="section section-alt">
        <div className="container">
          <SectionIntro
            locale={locale}
            kicker={L(c('تطبيقات أخرى', 'Other applications'), locale)}
            title={L(c('كمّل منظومتك', 'Complete your setup'), locale)}
          />
          <FeatureGrid locale={locale} items={others} />
        </div>
      </section>
    </>
  )
}
