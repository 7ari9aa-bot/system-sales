import React, { useState } from 'react'
import { Target, Check } from 'lucide-react'
import { c, tx, DetailHero, DemoBadge, Button } from '@/components/fihrist/Shared'

const plans = [
  { name: c('Starter', 'Starter'), body: c('للفريق الذي يريد أول Workflow واضح.', 'For a team that wants its first clear workflow.'), features: [c('حتى 5 مستخدمين', 'Up to 5 users'), c('Inbox تجريبي', 'Illustrative inbox'), c('قالب متابعة واحد', 'One follow-up template')] },
  { name: c('Growth', 'Growth'), body: c('لفريق يربط المحادثة بالطلب والمتابعة.', 'For a team connecting conversation to request and follow-up.'), features: [c('مسارات متعددة', 'Multiple workflows'), c('مساعد AI تجريبي', 'Illustrative AI assistant'), c('تقارير أساسية', 'Core reporting')] },
  { name: c('Enterprise', 'Enterprise'), body: c('للتكامل والحوكمة والتوسع حسب السوق.', 'For integrations, governance, and market-scale rollout.'), features: [c('صلاحيات وتدقيق', 'Permissions and audit'), c('خطة تنفيذ', 'Implementation plan'), c('دعم مخصص', 'Dedicated support')] },
]

export default function Pricing({ locale }) {
  const [billing, setBilling] = useState('monthly')
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الأسعار', 'Pricing')}
        title={c('خطط واضحة، بلا مفاجآت.', 'Clear plans, no surprises.')}
        body={c('هذه نسخة تصميمية تجريبية. الأرقام أدناه ليست عروضًا أو أسعارًا فعلية؛ الهدف هو اختبار بنية القرار.', 'This is a design prototype. The numbers below are not offers or real prices; they exist to test the decision structure.')}
        icon={Target}
      />
      <section className="section pricing-section">
        <div className="container">
          <div className="pricing-toolbar">
            <div>
              <span className="kicker">{tx(c('وحدة التسعير', 'Pricing unit'), locale)}</span>
              <strong>{tx(c('اختر الإيقاع الذي يناسب فريقك', 'Choose the rhythm for your team'), locale)}</strong>
            </div>
            <div className="billing-toggle" role="group" aria-label={tx(c('دورة الفوترة', 'Billing cycle'), locale)}>
              <button className={billing === 'monthly' ? 'active' : ''} onClick={() => setBilling('monthly')}>{tx(c('شهري', 'Monthly'), locale)}</button>
              <button className={billing === 'annual' ? 'active' : ''} onClick={() => setBilling('annual')}>{tx(c('سنوي', 'Annual'), locale)}<em>{tx(c('مرونة', 'flex'), locale)}</em></button>
            </div>
          </div>
          <div className="pricing-note">
            <DemoBadge locale={locale} />
            <span>{tx(c('الأرقام تجريبية حتى يتم اعتماد نموذج التسعير.', 'Numbers are illustrative until the pricing model is approved.'), locale)}</span>
          </div>
          <div className="pricing-grid">
            {plans.map((plan, i) => (
              <article className={`price-card ${i === 1 ? 'featured' : ''}`} key={plan.name.ar}>
                <span className="plan-kicker">0{i + 1} / {tx(c('خطة', 'PLAN'), locale)}</span>
                <h3>{tx(plan.name, locale)}</h3>
                <div className="price">{i < 2 ? '$—' : tx(c('تحدث معنا', 'Talk to us'), locale)}{i < 2 && <small>{tx(c(billing === 'monthly' ? 'شهري · تجريبي' : 'سنوي · تجريبي', billing === 'monthly' ? 'monthly · prototype' : 'annual · prototype'), locale)}</small>}</div>
                <p>{tx(plan.body, locale)}</p>
                <ul>{plan.features.map(f => <li key={f.ar}><Check size={15}/>{tx(f, locale)}</li>)}</ul>
                <Button href="/contact-sales" kind={i === 1 ? 'primary' : 'secondary'}>{tx(c(i === 2 ? 'اطلب عرضًا' : 'استكشف الخطة', i === 2 ? 'Request a demo' : 'Explore plan'), locale)}</Button>
              </article>
            ))}
          </div>
        </div>
      </section>

    </>
  )
}