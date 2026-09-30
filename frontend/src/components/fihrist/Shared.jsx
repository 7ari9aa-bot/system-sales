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
  return <span className="demo-badge"><span className="demo-dot" /> {tx(c('محتوى تجريبي', 'Demo content'), locale)}</span>
}

function SettingsIcon() { return <div className="rail-settings">•••</div> }

export function ProductFrame({ variant = 'inbox', locale }) {
  const isAr = locale === 'ar'
  const [activeThread, setActiveThread] = useState(0)
  const [filter, setFilter] = useState('all')
  const [approved, setApproved] = useState(false)
  const threadData = isAr ? [
    ['عميل محتمل — حساب تجريبي', 'هل العرض يشمل التوصيل؟', 'نية شراء عالية'],
    ['محادثة جديدة — حساب تجريبي', 'أرسل تفاصيل الطلب', 'طلب جديد'],
    ['متابعة — حساب تجريبي', 'متابعة بعد الاجتماع', 'متابعة'],
  ] : [
    ['Prospect — demo account', 'Does the quote include delivery?', 'High intent'],
    ['New thread — demo account', 'Sent order details', 'New request'],
    ['Follow-up — demo account', 'Post-meeting follow-up', 'Follow-up'],
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
      <div className="product-topbar"><div className="window-dots"><i/><i/><i/></div><span className="product-url">app.fihrist.demo / {variant}</span><span className="product-live"><span/> Live demo</span></div>
      <div className="product-body">
        <aside className="product-rail"><div className="rail-mark">F</div><Inbox size={17}/><Users size={17}/><Target size={17}/><WorkflowIcon size={17}/><SettingsIcon /></aside>
        <div className="product-main" dir="ltr">
          <div className="product-heading">
            <div>
              <span className="eyebrow-mini">{variant === 'inbox' ? 'INBOX / TODAY' : variant.toUpperCase() + ' / DEMO'}</span>
              <h3>{variant === 'inbox' ? (isAr ? 'المحادثات المهمة اليوم' : 'Priority conversations') : variant === 'assistant' ? (isAr ? 'اقتراحات المساعد' : 'Assistant suggestions') : variant === 'automation' ? (isAr ? 'متابعة عرض السعر' : 'Quote follow-up') : (isAr ? 'سجل العميل' : 'Customer record')}</h3>
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
                  {visibleThreads.map(([name, preview, badge], visibleIndex) => {
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
                  <div className="bubble ai"><Sparkles size={13}/>{isAr ? `استخرج النظام: ${active[2]} + خطوة تالية مقترحة` : `Extracted: ${active[2]} + suggested next action`}<small>{isAr ? 'اقتراح AI' : 'AI suggestion'}</small></div>
                  <div className="conversation-footer">
                    <span className="tag teal">{active[2]}</span>
                    <span className="tag">{isAr ? 'التالي: أرسل العرض' : 'Next: send quote'}</span>
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
                    <b>{variant === 'assistant' ? (isAr ? 'ملخص قابل للمراجعة' : 'Reviewable summary') : variant === 'automation' ? (isAr ? 'الخطوة التالية' : 'Next action') : (isAr ? 'سياق موثوق' : 'Trusted context')}</b>
                    <small>{variant === 'assistant' ? (isAr ? 'العميل يريد عرضاً خلال هذا الأسبوع.' : 'Customer needs a quote this week.') : variant === 'automation' ? (isAr ? 'أنشئ مهمة متابعة بعد 24 ساعة.' : 'Create a follow-up task in 24 hours.') : (isAr ? 'آخر طلب، المالك، ومصدر البيانات.' : 'Last order, owner, and data source.')}</small>
                  </span>
                </div>
                <div className="detail-line">
                  <span className="detail-icon sand"><Database size={15}/></span>
                  <span>
                    <b>{isAr ? 'المصدر' : 'Source'}</b>
                    <small>{isAr ? 'المحادثة #4821 · تمت المراجعة' : 'Conversation #4821 · Reviewed'}</small>
                  </span>
                </div>
                <div className="detail-actions">
                  <button onClick={() => setApproved(true)} className={approved ? 'is-approved' : ''}><Check size={14}/> {approved ? (isAr ? 'تم الاعتماد' : 'Approved') : (isAr ? 'اعتماد' : 'Approve')}</button>
                  <button className="muted">{isAr ? 'تعديل' : 'Edit'}</button>
                </div>
              </div>
              <div className="score-card">
                <span className="score-label">{isAr ? 'وضوح السياق' : 'Context clarity'}</span>
                <strong>86<span>%</span></strong>
                <div className="score-bar"><i/></div>
                <small>{isAr ? 'بيانات حديثة من 4 مصادر' : 'Fresh data from 4 sources'}</small>
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
    ? ['التقط الإشارة', 'افهم النية', 'عيّن المسؤول', 'تابع في الوقت المناسب', 'أغلق وتعلّم']
    : ['Capture the signal', 'Understand intent', 'Assign ownership', 'Follow up on time', 'Close and learn']
  const defaultDescs = locale === 'ar'
    ? ['رسالة تصل من أي قناة، بلا نسخ ولصق', 'يفهم النظام: استفسار؟ طلب؟ شكوى؟', 'لكل محادثة صاحب وموعد استجابة', 'تذكير وقالب رد قبل أن يبرد العميل', 'النتيجة تتحول إلى بيانات تحسّن ما بعدها']
    : ['A message arrives from any channel—no copy-paste', 'The system reads intent: question, order, complaint', 'Every thread gets an owner and response window', 'A reminder and reply draft before the lead goes cold', 'The outcome becomes data for the next round']
  const steps = customSteps || defaultSteps
  const descs = customDescs || defaultDescs
  return (
    <div className={`workflow ${compact ? 'compact' : ''}`}>
      {steps.map((step, i) => (
        <div className="workflow-step" key={step}>
          <span className="step-number">0{i + 1}</span>
          <span>{step}</span>
          {!compact && <small className="step-desc">{descs[i]}</small>}
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
        <span>Core workflow</span>
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