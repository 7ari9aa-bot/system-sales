import React, { useState } from 'react'
import { Target, Check } from 'lucide-react'
import { c, tx, DetailHero, Button } from '@/components/fihrist/Shared'

const plans = [
  { name: c('Starter', 'Starter'), monthlyPrice: c('تواصل معنا', 'Contact sales'), annualPrice: c('تواصل معنا', 'Contact sales'), body: c('تواصل معنا لمعرفة الخيارات المتاحة لمتجرك.', 'Contact us to discuss the options for your store.'), features: [c('السعر وتفاصيل الخطة عند التواصل', 'Ask our team for pricing and plan details')] },
  { name: c('Pro', 'Pro'), monthlyPrice: c('تواصل معنا', 'Contact sales'), annualPrice: c('تواصل معنا', 'Contact sales'), body: c('ناقش احتياجات فريقك والخيارات المتاحة.', 'Discuss your team\'s needs and available options.'), features: [c('السعر وتفاصيل الخطة عند التواصل', 'Ask our team for pricing and plan details')] },
  { name: c('Enterprise', 'Enterprise'), monthlyPrice: c('تواصل معنا', 'Contact sales'), annualPrice: c('تواصل معنا', 'Contact sales'), body: c('تحدث مع فريقنا عن احتياجات متجرك.', 'Talk with our team about your store\'s needs.'), features: [c('السعر وتفاصيل الخطة عند التواصل', 'Ask our team for pricing and plan details')] },
]

export default function Pricing({ locale }) {
  const [billing, setBilling] = useState('monthly')
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الأسعار', 'Pricing')}
        title={c('تعرّف على خيارات FIHRIST.', 'Explore FIHRIST plan options.')}
        body={c('تواصل مع فريق FIHRIST لمعرفة تفاصيل الخطط والأسعار المتاحة.', 'Contact the FIHRIST team for current plan and pricing details.')}
        icon={Target}
      />
      <section className="section pricing-section">
        <div className="container">
          <div className="pricing-toolbar">
            <div>
              <span className="kicker">{tx(c('خيارات الخطط', 'Plan options'), locale)}</span>
              <strong>{tx(c('استفسر عن تفاصيل الدفع', 'Ask about billing options'), locale)}</strong>
            </div>
            <div className="billing-toggle" role="group" aria-label={tx(c('دورة الفوترة', 'Billing cycle'), locale)}>
              <button className={billing === 'monthly' ? 'active' : ''} onClick={() => setBilling('monthly')}>{tx(c('شهري', 'Monthly'), locale)}</button>
              <button className={billing === 'annual' ? 'active' : ''} onClick={() => setBilling('annual')}>{tx(c('سنوي', 'Annual'), locale)}</button>
            </div>
          </div>
          <div className="pricing-note">
            <span className="demo-badge"><span className="demo-dot" /> {tx(c('الأسعار عبر فريقنا', 'Pricing via our team'), locale)}</span>
            <span>{tx(c(billing === 'annual' ? 'تواصل معنا لمعرفة تفاصيل الدفع السنوي.' : 'تواصل معنا لمعرفة تفاصيل الدفع الشهري.', billing === 'annual' ? 'Contact us for details about annual billing.' : 'Contact us for details about monthly billing.'), locale)}</span>
          </div>
          <div className="pricing-grid">
            {plans.map((plan, i) => (
              <article className={`price-card ${i === 1 ? 'featured' : ''}`} key={plan.name.ar}>
                <span className="plan-kicker">0{i + 1} / {tx(c('خطة', 'PLAN'), locale)}</span>
                <h3>{tx(plan.name, locale)}</h3>
                <div className="price">
                  {tx(billing === 'annual' ? plan.annualPrice : plan.monthlyPrice, locale)}
                  <small>{tx(c('السعر وتفاصيل الخطة عند التواصل', 'Ask our team for pricing and plan details'), locale)}</small>
                </div>
                <p>{tx(plan.body, locale)}</p>
                <ul>{plan.features.map(f => <li key={f.ar}><Check size={15}/>{tx(f, locale)}</li>)}</ul>
                <Button href="/contact-sales" kind={i === 1 ? 'primary' : 'secondary'}>{tx(c('استفسر عن الخطة', 'Ask about this plan'), locale)}</Button>
              </article>
            ))}
          </div>
        </div>
      </section>

    </>
  )
}
