import React, { useState } from 'react'
import { MessageCircle, Check, ArrowRight } from 'lucide-react'
import { c, tx, DetailHero, SectionIntro, DemoBadge } from '@/components/fihrist/Shared'

export default function ContactSales({ locale }) {
  const [sent, setSent] = useState(false)
  const [focus, setFocus] = useState('workflow')

  if (sent) {
    return (
      <>
        <DetailHero
          locale={locale}
          kicker={c('تواصل مع المبيعات', 'Contact sales')}
          title={c('اجعل الجلسة الأولى مفيدة.', 'Make the first conversation useful.')}
          body={c('اختر المسار الذي تريد مناقشته وسنبدأ من السياق الصحيح.', 'Choose what you want to discuss and we\'ll start with the right context.')}
          icon={MessageCircle}
        />
        <section className="section contact-section" id="form">
          <div className="container form-success">
            <span className="success-mark"><Check size={22}/></span>
            <span className="kicker">{tx(c('انتهت معاينة النموذج', 'Form preview complete'), locale)}</span>
            <h2>{tx(c('الطلب لم يُرسل.', 'Your request was not sent.'), locale)}</h2>
            <p>{tx(c('هذه معاينة فقط؛ لم يتم حفظ بريدك أو ملاحظتك أو إرسالها.', 'This is only a preview. Your email and note were not saved or sent.'), locale)}</p>
            <button className="btn btn-secondary" onClick={() => setSent(false)}>{tx(c('معاينة النموذج مرة أخرى', 'Preview the form again'), locale)}</button>
          </div>
        </section>

      </>
    )
  }

  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('تواصل مع المبيعات', 'Contact sales')}
        title={c('اجعل الجلسة الأولى مفيدة.', 'Make the first conversation useful.')}
        body={c('اختر المسار الذي تريد مناقشته: Workflow، تكامل، ترحيل، أو حوكمة — وسنبدأ من السياق الصحيح.', 'Choose what you want to discuss: workflow, integrations, migration, or governance—and start with the right context.')}
        icon={MessageCircle}
        ctaLabel={c('احجز جلسة', 'Book a session')}
        ctaHref="#form"
      />
      <section className="section contact-section" id="form">
        <div className="container contact-grid">
          <div>
            <span className="kicker">{tx(c('جلسة تعريفية', 'Introductory session'), locale)}</span>
            <h2>{tx(c('أخبرنا أين تتعطل الخطوة التالية.', 'Tell us where the next action gets stuck.'), locale)}</h2>
            <p>{tx(c('اختر المسار وأضف بريدك. سنبقي هذه التجربة واضحة ومحددة.', 'Choose a path and add your email. We keep this demo focused and specific.'), locale)}</p>
          </div>
          <form className="contact-form" onSubmit={(event) => { event.preventDefault(); setSent(true) }}>
            <label>{tx(c('البريد المهني', 'Work email'), locale)}
              <input type="email" required placeholder="you@company.com" />
            </label>
            <label>{tx(c('المسار الأقرب', 'Closest path'), locale)}
              <select value={focus} onChange={(event) => setFocus(event.target.value)}>
                <option value="workflow">{tx(c('وضوح الـWorkflow', 'Workflow clarity'), locale)}</option>
                <option value="context">{tx(c('سياق العميل', 'Customer context'), locale)}</option>
                <option value="governance">{tx(c('الحوكمة والتكامل', 'Governance & integrations'), locale)}</option>
              </select>
            </label>
            <label>{tx(c('ملاحظة قصيرة', 'A short note'), locale)}
              <textarea rows={3} placeholder={tx(c('ما الذي تريد أن تراه في الجلسة؟', 'What should we cover?'), locale)} />
            </label>
            <button className="btn btn-primary" type="submit">
              {tx(c('معاينة النموذج', 'Preview the form'), locale)}
              <ArrowRight size={16}/>
            </button>
            <small>{tx(c('المحتوى المعروض توضيحي', 'Displayed content is illustrative'), locale)}</small>
          </form>
        </div>
      </section>

    </>
  )
}