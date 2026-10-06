import React, { useEffect, useRef, useState } from 'react'
import {
  ArrowRight, Check, Database, Inbox, Search, SlidersHorizontal,
  Sparkles, Target, Users, Workflow as WorkflowIcon,
} from 'lucide-react'

const c = (ar, en) => ({ ar, en })
const tx = (copy, locale) => copy[locale]

export { c, tx }

export function Reveal({ children, className = '' }) {
  const ref = useRef(null)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || element.getBoundingClientRect().top <= window.innerHeight) {
      element.classList.add('reveal-in')
      return
    }
    element.classList.add('reveal-pre')
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { element.classList.add('reveal-in'); observer.disconnect() }
    }, { threshold: 0.1 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return <div ref={ref} className={`reveal ${className}`}>{children}</div>
}

export function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || element.getBoundingClientRect().top <= window.innerHeight) {
      element.classList.add('reveal-in'); return
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { element.classList.add('reveal-in'); observer.disconnect() }
    }, { threshold: 0.1 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return ref
}

export function SectionIntro({ kicker, title, body, align = 'center' }) {
  return (
    <Reveal className={`section-intro align-${align}`}>
      <span className="kicker">{kicker}</span>
      <h2>{title}</h2>
      {body && <p>{body}</p>}
    </Reveal>
  )
}

export function Button({ children, href = '#', kind = 'primary', icon = true }) {
  return (
    <a className={`btn btn-${kind}`} href={href}>
      {children}
      {icon && <ArrowRight size={16} aria-hidden="true" />}
    </a>
  )
}

export function DemoBadge({ locale = 'ar' }) {
  return <span className="demo-badge"><span className="demo-dot" /> {tx(c('معاينة توضيحية', 'Illustrative preview'), locale)}</span>
}

function SettingsIcon() { return <div className="rail-settings">•••</div> }

export function ProductFrame({ variant = 'inbox', locale }) {
  const isAr = locale === 'ar'
  const [activeThread, setActiveThread] = useState(0)
  const [filter, setFilter] = useState('all')
  const [approved, setApproved] = useState(false)
  const threadData = isAr ? [
    ['محادثة جديدة', 'العميل يسأل عن المقاس والتوفر.', 'استفسار عن المنتج'],
    ['طلب جديد', 'أرسل تفاصيل المنتج المتاحة.', 'طلب جديد'],
    ['متابعة العميل', 'لم يصلنا رد بعد.', 'متابعة'],
  ] : [
    ['New conversation', 'Customer asks about size and availability.', 'Product question'],
    ['New order', 'Sent the available product details.', 'New order'],
    ['Customer follow-up', 'No reply yet.', 'Follow-up'],
  ]
  useEffect(() => {
    if (variant !== 'inbox') return
    const timer = window.setInterval(() => setActiveThread((value) => (value + 1) % threadData.length), 4500)
    return () => window.clearInterval(timer)
  }, [variant, threadData.length])
  const visibleThreads = filter === 'all' ? threadData : filter === 'priority' ? threadData.slice(0, 2) : threadData.slice(1)
  const active = threadData[activeThread] || threadData[0]
  return (
    <div className={`product-frame product-${variant}`} dir="ltr" aria-label={isAr ? 'لقطة تجريبية من واجهة FIHRIST' : 'Illustrative FIHRIST product interface'}>
      <div className="product-topbar"><div className="window-dots"><i/><i/><i/></div><span className="product-url">FIHRIST / {variant}</span><span className="product-live"><span/> Preview</span></div>
      <div className="product-body">
        <aside className="product-rail"><div className="rail-mark">F</div><Inbox size={17}/><Users size={17}/><Target size={17}/><WorkflowIcon size={17}/><SettingsIcon /></aside>
        <div className="product-main" dir="ltr">
          <div className="product-heading">
            <div>
              <span className="eyebrow-mini">{variant === 'inbox' ? 'INBOX / TODAY' : variant.toUpperCase()}</span>
              <h3>{variant === 'inbox' ? (isAr ? 'المحادثات المهمة اليوم' : 'Priority conversations') : variant === 'assistant' ? (isAr ? 'اقتراحات المساعد' : 'Assistant suggestions') : variant === 'automation' ? (isAr ? 'متابعة العميل' : 'Customer follow-up') : (isAr ? 'سجل العميل' : 'Customer record')}</h3>
            </div>
            <span className="avatar">أ</span>
          </div>
          {variant === 'inbox' && (
            <>
              <div className="demo-toolbar">
                <div className="demo-search"><Search size={13}/><span>{isAr ? 'ابحث في المحادثات...' : 'Search conversations...'}</span></div>
                <div className="demo-tabs">
                  {[['all', isAr ? 'الكل' : 'All'], ['priority', isAr ? 'مهم' : 'Priority'], ['unread', isAr ? 'غير مقروء' : 'Unread']].map(([key, label]) => (
                    <button key={key} className={filter === key ? 'active' : ''} onClick={() => { setFilter(key); setActiveThread(0) }}>{label}</button>
                  ))}
                </div>
                <button className="demo-filter" aria-label={isAr ? 'تصفية' : 'Filter'}><SlidersHorizontal size={13}/></button>
              </div>
              <div className="inbox-layout">
                <div className="thread-list">
                  {visibleThreads.map(([name, preview], visibleIndex) => {
                    const i = filter === 'unread' ? visibleIndex + 1 : visibleIndex
                    return (
                      <button className={`thread ${i === activeThread ? 'active' : ''}`} key={name} onClick={() => setActiveThread(i)} aria-pressed={i === activeThread}>
                        <span className={`thread-avatar ${i === 1 ? 'gray' : i === 2 ? 'sand' : ''}`}>{name[0]}</span>
                        <span><b>{name}</b><small>{preview}</small></span>
                        <em>{i === activeThread ? (isAr ? 'الآن' : 'now') : `${i + 1}${isAr ? 'س' : 'h'}`}</em>
                      </button>
                    )
                  })}
                </div>
                <div className="conversation">
                  <div className="bubble customer">{active[1]}<small>10:42</small></div>
                  <div className="bubble ai"><Sparkles size={13}/>{isAr ? `سؤال العميل: ${active[2]} + خطوة تالية مقترحة` : `Customer request: ${active[2]} + suggested next step`}<small>{isAr ? 'مساعدة AI' : 'AI assistance'}</small></div>
                  <div className="conversation-footer">
                    <span className="tag teal">{active[2]}</span>
                    <span className="tag">{isAr ? 'التالي: أرسل تفاصيل المنتج المتاحة' : 'Next: send the available product details'}</span>
                  </div>
                </div>
              </div>
            </>
          )}
          {variant !== 'inbox' && (
            <div className="detail-layout">
              <div className="detail-card">
                <div className="detail-line">
                  <span className="detail-icon teal"><Sparkles size={15}/></span>
                  <span>
                    <b>{variant === 'assistant' ? (isAr ? 'ملخص المحادثة' : 'Conversation summary') : variant === 'automation' ? (isAr ? 'الخطوة التالية' : 'Next action') : (isAr ? 'سياق موثوق' : 'Trusted context')}</b>
                    <small>{variant === 'assistant' ? (isAr ? 'العميل يسأل عن المقاس والتوفر.' : 'Customer asks about size and availability.') : variant === 'automation' ? (isAr ? 'أنشئ مهمة متابعة عند الحاجة.' : 'Create a follow-up task when needed.') : (isAr ? 'آخر طلب، المسؤول، ومعلومات المنتج.' : 'Latest order, owner, and product details.')}</small>
                  </span>
                </div>
                <div className="detail-line">
                  <span className="detail-icon sand"><Database size={15}/></span>
                  <span>
                    <b>{isAr ? 'المصدر' : 'Source'}</b>
                    <small>{isAr ? 'محادثة العميل · متاحة للفريق' : 'Customer conversation · available to your team'}</small>
                  </span>
                </div>
                <div className="detail-actions">
                  <button onClick={() => setApproved(true)} className={approved ? 'is-approved' : ''}><Check size={14}/> {approved ? (isAr ? 'تمت المراجعة' : 'Reviewed') : (isAr ? 'مراجعة المحادثة' : 'Review conversation')}</button>
                  <button className="muted">{isAr ? 'تعديل' : 'Edit'}</button>
                </div>
              </div>
              <div className="score-card">
                <span className="score-label">{isAr ? 'سياق البيع' : 'Sales context'}</span>
                <strong>✓</strong>
                <div className="score-bar"><i/></div>
                <small>{isAr ? 'محادثة · منتج · طلب' : 'Conversation · product · order'}</small>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function Workflow({ locale, compact = false, steps: customSteps, descs: customDescs }) {
  const defaultSteps = locale === 'ar'
    ? ['ابدأ من سؤال العميل', 'اربط العميل بالمنتج', 'سجّل الطلب والبيع', 'حدّث المخزون بما بيع وما بقي', 'تابع الخطوة التالية واقرأ الأداء']
    : ['Start with a customer question', 'Connect the customer and product', 'Record the order and sale', 'Update inventory with what sold and what remains', 'Follow up and review performance']
  const defaultDescs = locale === 'ar'
    ? ['رسالة من إحدى قنوات التواصل المدعومة', 'سجل العميل وتفاصيل المنتج المتاحة للفريق', 'اربط الطلب بالمحادثة وسجّل المنتج والاختيار والكمية التي بيعت', 'تعرّف على ما بيع وما بقي في المخزون', 'استخدم تذكيرًا أو قاعدة متابعة؛ وتساعد بيانات المتجر على قراءة الأداء']
    : ['A message arrives through a supported channel', 'Customer context and available product details are at hand', 'Connect the order to the conversation and record the product, option, and quantity sold', 'See what sold and what remains in inventory', 'Use a reminder or follow-up rule; store data also supports performance insights']
  const steps = customSteps || defaultSteps
  const descs = customDescs || defaultDescs
  const localized = (value) => (typeof value === 'string' ? value : tx(value, locale))
  return (
    <div className={`workflow ${compact ? 'compact' : ''}`}>
      {steps.map((step, i) => (
        <div className="workflow-step" key={i}>
          <span className="step-number">0{i + 1}</span>
          <span>{localized(step)}</span>
          {!compact && <small className="step-desc">{localized(descs[i])}</small>}
          {i < steps.length - 1 && <span className="step-line" />}
        </div>
      ))}
    </div>
  )
}



export function PrincipleCard({ icon: Icon, locale, title }) {
  return (
    <div className="principle-card">
      <span className="principle-mark"><Icon size={26}/></span>
      <DemoBadge locale={locale}/>
      {title && <h3>{tx(title, locale)}</h3>}
      <Workflow locale={locale} compact/>
      <div className="principle-foot">
        <span>{tx(c('مسار البيع', 'Sales journey'), locale)}</span>
        <span className="tag teal">{tx(c('توضيحي', 'Illustrative'), locale)}</span>
      </div>
    </div>
  )
}

export function DetailHero({ locale, kicker, title, body, icon: Icon, variant, ctaLabel, ctaHref }) {
  return (
    <section className="detail-hero">
      <div className="container detail-grid">
        <div>
          <span className="eyebrow"><Icon size={15}/> {tx(kicker, locale)}</span>
          <h1>{tx(title, locale)}</h1>
          <p className="hero-lede">{tx(body, locale)}</p>
          <div className="hero-actions">
            <Button href={ctaHref || '#start'}>{tx(ctaLabel || c('استكشف الآن', 'Explore now'), locale)}</Button>
            <Button href="/product" kind="secondary">{tx(c('شاهد المنصة', 'See the platform'), locale)}</Button>
          </div>
        </div>
        <div className="detail-visual">
          {variant
            ? <ProductFrame locale={locale} variant={variant}/>
            : <PrincipleCard icon={Icon} locale={locale} />}
        </div>
      </div>
    </section>
  )
}

export function FeatureGrid({ items, locale }) {
  return (
    <div className="feature-grid">
      {items.map(({ icon: Icon, title, body, href }, i) => (
        <FeatureGridItem key={title.ar} Icon={Icon} title={title} body={body} href={href} locale={locale} index={i} />
      ))}
    </div>
  )
}

function FeatureGridItem({ Icon, title, body, href, locale, index }) {
  const ref = useReveal()
  return (
    <article className="feature-card reveal" ref={ref} style={{ transitionDelay: `${index * 70}ms` }}>
      <span className="icon-tile"><Icon size={20}/></span>
      <h3>{tx(title, locale)}</h3>
      <p>{tx(body, locale)}</p>
      {href && <a href={href}>{tx(c('استكشف', 'Explore'), locale)} <ArrowRight size={15}/></a>}
    </article>
  )
}

export function DetailPoints({ points, locale }) {
  return (
    <div className="detail-points">
      {points.map((point, i) => (
        <DetailPointItem key={i} point={point} locale={locale} index={i} />
      ))}
    </div>
  )
}

function DetailPointItem({ point, locale, index }) {
  const ref = useReveal()
  return (
    <article className="reveal" ref={ref} style={{ transitionDelay: `${index * 70}ms` }}>
      <span className="point-index">0{index + 1}</span>
      <div>
        <h3>{tx(point.title, locale)}</h3>
        <p>{tx(point.body, locale)}</p>
      </div>
    </article>
  )
}
