import React, { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Bot, Check, CircleHelp, Database, FileText, Globe2, Inbox, Layers3,
  LockKeyhole, Menu, MessageCircle, Moon, Network, Search, ShieldCheck,
  SlidersHorizontal, Sparkles, Sun, Target, Users, Workflow as WorkflowIcon, X, Zap,
} from 'lucide-react'
import Product from '@/pages/fhrist/Product'
import Conversations from '@/pages/fhrist/Conversations'
import Context from '@/pages/fhrist/Context'
import Assistant from '@/pages/fhrist/Assistant'
import Automation from '@/pages/fhrist/Automation'
import Pricing from '@/pages/fhrist/Pricing'
import Security from '@/pages/fhrist/Security'
import Privacy from '@/pages/fhrist/Privacy'
import Terms from '@/pages/fhrist/Terms'
import Support from '@/pages/fhrist/Support'
import ContactSales from '@/pages/fhrist/ContactSales'
import InteractiveBackground from '@/components/InteractiveBackground'
import HeroRelationCanvas from '@/components/HeroRelationCanvas'
import Spotlight from '@/components/Spotlight'
import { getTokens } from '@/lib/api'

const c = (ar, en) => ({ ar, en })
const tx = (copy, locale) => copy[locale]

const navItems = [
  { href: '/product', label: c('المنصة', 'Platform') },
  { href: '/conversations', label: c('المحادثات', 'Conversations') },
  { href: '/assistant', label: c('AI', 'AI') },
  { href: '/pricing', label: c('الأسعار', 'Pricing') },
  { href: '/security', label: c('الأمان', 'Security') },
]

const pageFromPath = () => {
  const path = window.location.pathname.replace(/\/$/, '')
  if (path === '') return 'home'
  const key = path.slice(1)
  return ['product','conversations','context','assistant','automation','pricing','security','privacy','terms','contact-sales','support'].includes(key) ? key : 'home'
}

const pageMeta = {
  home: c('مبيعات أوضح، من أول محادثة إلى الإغلاق', 'Clearer sales, from first conversation to close'),
  product: c('المنصة — FIHRIST Sales OS', 'Platform — FIHRIST Sales OS'),
  conversations: c('المحادثات التي تتحول إلى عمل', 'Conversations that become action'),
  context: c('سياق العميل في مكان واحد', 'Customer context in one place'),
  assistant: c('AI يقترح، وفريقك يقرر', 'AI that suggests, your team decides'),
  automation: c('أتمتة قابلة للفهم والضبط', 'Automation you can understand and control'),
  pricing: c('خطط واضحة، بلا مفاجآت', 'Clear plans, no surprises'),
  security: c('ثقة يمكن مراجعتها', 'Trust you can review'),
  privacy: c('سياسة الخصوصية', 'Privacy policy'),
  terms: c('شروط الاستخدام', 'Terms of use'),
  'contact-sales': c('تحدث مع خبير مبيعات', 'Talk to a sales expert'),
  support: c('ابدأ من هنا', 'Start here'),
}

function KineticHeadline({ locale }) {
  const words = locale === 'ar' ? ['فوضى.', 'فجوات.', 'تخمين.'] : ['chaos.', 'gaps.', 'guesswork.']
  const [index, setIndex] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => setIndex((value) => (value + 1) % words.length), 2600); return () => window.clearInterval(timer) }, [words.length])
  return <h1>{tx(c('مبيعات بلا', 'Sales without'), locale)} <span className="kinetic-slot">{words.map((w, i) => <span key={w} className={i === index ? 'kinetic-word on' : 'kinetic-word'} aria-hidden={i !== index}>{w}</span>)}</span><br/>{tx(c('من أول محادثة إلى الإغلاق.', 'from first conversation to close.'), locale)}</h1>
}

function Reveal({ children, className = '' }) {
  const ref = React.useRef(null)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || element.getBoundingClientRect().top <= window.innerHeight) { element.classList.add('reveal-in'); return }
    element.classList.add('reveal-pre')
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { element.classList.add('reveal-in'); observer.disconnect() } }, { threshold: 0.1 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return <div ref={ref} className={`reveal ${className}`}>{children}</div>
}

function ThemeIcon({ theme }) {
  return theme === 'dark' ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />
}

function Logo({ compact = false }) {
  return <a className="brand" href="/" aria-label="FIHRIST home"><img src="/fihrist-mark.svg" alt="" /><span className={compact ? 'sr-only' : ''}>FIHRIST</span></a>
}

function Button({ children, href = '#', kind = 'primary', icon = true }) {
  return <a className={`btn btn-${kind}`} href={href} data-testid={`link-${String(children).slice(0, 18).replace(/\s+/g, '-').toLowerCase()}`}>{children}{icon && <ArrowRight size={16} aria-hidden="true" />}</a>
}

function DemoBadge({ locale = 'ar' }) { return <span className="demo-badge"><span className="demo-dot" /> {tx(c('محتوى تجريبي', 'Demo content'), locale)}</span> }

function ProductFrame({ variant = 'inbox', locale }) {
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
  useEffect(() => { if (variant !== 'inbox') return; const timer = window.setInterval(() => setActiveThread((value) => (value + 1) % threadData.length), 4500); return () => window.clearInterval(timer) }, [variant, threadData.length])
  const visibleThreads = filter === 'all' ? threadData : filter === 'priority' ? threadData.slice(0, 2) : threadData.slice(1)
  const active = threadData[activeThread] || threadData[0]
  return <div className={`product-frame product-${variant}`} dir="ltr" aria-label={isAr ? 'لقطة تجريبية من واجهة FIHRIST' : 'Illustrative FIHRIST product interface'}>
    <div className="product-topbar"><div className="window-dots"><i/><i/><i/></div><span className="product-url">app.fihrist.demo / {variant}</span><span className="product-live"><span/> Live demo</span></div>
    <div className="product-body">
      <aside className="product-rail"><div className="rail-mark">F</div><Inbox size={17}/><Users size={17}/><Target size={17}/><WorkflowIcon size={17}/><SettingsIcon /></aside>
      <div className="product-main" dir="ltr">
        <div className="product-heading"><div><span className="eyebrow-mini">{variant === 'inbox' ? 'INBOX / TODAY' : variant.toUpperCase() + ' / DEMO'}</span><h3>{variant === 'inbox' ? (isAr ? 'المحادثات المهمة اليوم' : 'Priority conversations') : variant === 'assistant' ? (isAr ? 'اقتراحات المساعد' : 'Assistant suggestions') : variant === 'automation' ? (isAr ? 'متابعة عرض السعر' : 'Quote follow-up') : (isAr ? 'سجل العميل' : 'Customer record')}</h3></div><span className="avatar">أ</span></div>
        {variant === 'inbox' && <><div className="demo-toolbar"><div className="demo-search"><Search size={13}/><span>{isAr ? 'ابحث في المحادثات...' : 'Search conversations...'}</span></div><div className="demo-tabs">{[['all', isAr ? 'الكل' : 'All'], ['priority', isAr ? 'مهم' : 'Priority'], ['unread', isAr ? 'غير مقروء' : 'Unread']].map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => { setFilter(key); setActiveThread(0) }}>{label}</button>)}</div><button className="demo-filter" aria-label={isAr ? 'تصفية' : 'Filter'}><SlidersHorizontal size={13}/></button></div><div className="inbox-layout"><div className="thread-list">{visibleThreads.map(([name, preview, badge], visibleIndex) => { const i = filter === 'unread' ? visibleIndex + 1 : visibleIndex; return ( <button className={`thread ${i === activeThread ? 'active' : ''}`} key={name} onClick={() => setActiveThread(i)} aria-pressed={i === activeThread}><span className={`thread-avatar ${i === 1 ? 'gray' : i === 2 ? 'sand' : ''}`}>{name[0]}</span><span><b>{name}</b><small>{preview}</small></span><em>{i === activeThread ? (isAr ? 'الآن' : 'now') : `${i + 1}${isAr ? 'س' : 'h'}`}</em></button>)})}</div><div className="conversation"><div className="bubble customer">{active[1]}<small>10:42</small></div><div className="bubble ai"><Sparkles size={13}/>{isAr ? `استخرج النظام: ${active[2]} + خطوة تالية مقترحة` : `Extracted: ${active[2]} + suggested next action`}<small>{isAr ? 'اقتراح AI' : 'AI suggestion'}</small></div><div className="conversation-footer"><span className="tag teal">{active[2]}</span><span className="tag">{isAr ? 'التالي: أرسل العرض' : 'Next: send quote'}</span></div></div></div></>}
         {variant !== 'inbox' && <div className="detail-layout"><div className="detail-card"><div className="detail-line"><span className="detail-icon teal"><Sparkles size={15}/></span><span><b>{variant === 'assistant' ? (isAr ? 'ملخص قابل للمراجعة' : 'Reviewable summary') : variant === 'automation' ? (isAr ? 'الخطوة التالية' : 'Next action') : (isAr ? 'سياق موثوق' : 'Trusted context')}</b><small>{variant === 'assistant' ? (isAr ? 'العميل يريد عرضاً خلال هذا الأسبوع.' : 'Customer needs a quote this week.') : variant === 'automation' ? (isAr ? 'أنشئ مهمة متابعة بعد 24 ساعة.' : 'Create a follow-up task in 24 hours.') : (isAr ? 'آخر طلب، المالك، ومصدر البيانات.' : 'Last order, owner, and data source.')}</small></span></div><div className="detail-line"><span className="detail-icon sand"><Database size={15}/></span><span><b>{isAr ? 'المصدر' : 'Source'}</b><small>{isAr ? 'المحادثة #4821 · تمت المراجعة' : 'Conversation #4821 · Reviewed'}</small></span></div><div className="detail-actions"><button onClick={() => setApproved(true)} className={approved ? 'is-approved' : ''}><Check size={14}/> {approved ? (isAr ? 'تم الاعتماد' : 'Approved') : (isAr ? 'اعتماد' : 'Approve')}</button><button className="muted">{isAr ? 'تعديل' : 'Edit'}</button></div></div><div className="score-card"><span className="score-label">{isAr ? 'وضوح السياق' : 'Context clarity'}</span><strong>86<span>%</span></strong><div className="score-bar"><i/></div><small>{isAr ? 'بيانات حديثة من 4 مصادر' : 'Fresh data from 4 sources'}</small></div></div>}
      </div>
    </div>
  </div>
}
function SettingsIcon(){ return <div className="rail-settings">•••</div> }

function CommandPalette({ locale, onClose }) {
  const [query, setQuery] = useState('')
  const commands = [
    ...navItems,
    { href: '/context', label: c('السياق', 'Context') },
    { href: '/automation', label: c('الأتمتة', 'Automation') },
    { href: '/contact-sales', label: c('تواصل مع المبيعات', 'Contact sales') },
  ]
  const filtered = commands.filter((item) => `${item.label.ar} ${item.label.en}`.toLowerCase().includes(query.toLowerCase()))
  return <div className="command-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="command-panel" role="dialog" aria-modal="true" aria-label={locale === 'ar' ? 'بحث سريع' : 'Quick search'}>
      <div className="command-heading"><Search size={17}/><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={locale === 'ar' ? 'ابحث في FIHRIST...' : 'Search FIHRIST...'} aria-label={locale === 'ar' ? 'ابحث في الصفحات' : 'Search pages'} data-testid="input-command-search"/><kbd>ESC</kbd></div>
      <div className="command-results">{filtered.map((item) => <a href={item.href} key={item.href} onClick={onClose} data-testid={`link-command-${item.href.slice(1).replace('/', '-')}`}><span>{tx(item.label, locale)}</span><ArrowRight size={15}/></a>)}{filtered.length === 0 && <p className="command-empty">{locale === 'ar' ? 'لا توجد نتائج مطابقة.' : 'No matching pages.'}</p>}</div>
      <div className="command-foot"><span>{locale === 'ar' ? 'تنقل سريع بين مسارات المنتج' : 'Quick navigation across product paths'}</span><span>⌘ K</span></div>
    </section>
  </div>
}

function Header({ locale, setLocale, theme, toggleTheme }) {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  useEffect(() => { const onScroll = () => setScrolled(window.scrollY > 8); onScroll(); window.addEventListener('scroll', onScroll, { passive: true }); setAuthed(Boolean(getTokens())); return () => window.removeEventListener('scroll', onScroll) }, [])
  useEffect(() => { const onKey = (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setCommandOpen(true) } if (event.key === 'Escape') setCommandOpen(false) }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [])
  return <><header className={`site-header ${scrolled ? 'is-scrolled' : ''}`}><div className="container header-inner"><Logo/><nav id="site-primary-navigation" className={open ? 'nav open' : 'nav'} aria-label={locale === 'ar' ? 'التنقل الرئيسي' : 'Primary navigation'}>{navItems.map(item => <a key={item.href} href={item.href}>{tx(item.label, locale)}</a>)}<a href="/contact-sales">{tx(c('تواصل معنا','Contact sales'), locale)}</a><div className="mobile-nav-actions">{authed ? <a href="/dashboard">{tx(c('فتح التطبيق','Open app'), locale)}</a> : <><a href="/login">{tx(c('تسجيل الدخول','Sign in'), locale)}</a><a href="/register">{tx(c('ابدأ الآن','Start now'), locale)}</a></>}</div></nav><div className="header-actions"><button className="theme-switch" onClick={toggleTheme} aria-label={locale === 'ar' ? 'تبديل الوضع' : 'Toggle theme'} title={locale === 'ar' ? 'تبديل الوضع' : 'Toggle theme'} data-testid="button-toggle-theme"><ThemeIcon theme={theme}/></button><button className="lang-switch" onClick={() => setLocale(locale === 'ar' ? 'en' : 'ar')} aria-label={locale === 'ar' ? 'تغيير اللغة' : 'Switch language'} data-testid="button-toggle-language"><Globe2 size={15}/><span>{locale === 'ar' ? 'EN' : 'عربي'}</span></button>{authed ? <Button href="/dashboard" kind="primary">{tx(c('فتح التطبيق','Open app'), locale)}</Button> : <><a className="login-link" href="/login">{tx(c('تسجيل الدخول','Sign in'), locale)}</a><Button href="/register" kind="primary">{tx(c('ابدأ الآن','Start now'), locale)}</Button></>}<button className="menu-button" onClick={() => setOpen(!open)} aria-label={open ? (locale === 'ar' ? 'إغلاق القائمة' : 'Close menu') : (locale === 'ar' ? 'فتح القائمة' : 'Open menu')} aria-expanded={open} aria-controls="site-primary-navigation" data-testid="button-toggle-menu">{open ? <X/> : <Menu/>}</button></div></div></header>{commandOpen && <CommandPalette locale={locale} onClose={() => setCommandOpen(false)}/>}</>
}

function TrustStrip({ locale }) { return <section className="trust-strip"><div className="container trust-inner"><span>{tx(c('مصمم لفرق المبيعات التي لا تريد فقدان أي فرصة', 'For sales teams that refuse to lose the next action'), locale)}</span><div className="trust-names"><b>ALMADA</b><b>nūr</b><b>AFQ</b><b>رام</b><b>مدار</b></div><DemoBadge/></div></section> }

function Workflow({ locale, compact = false }) {
  const steps = locale === 'ar' ? ['التقط الإشارة','افهم النية','عيّن المسؤول','تابع في الوقت المناسب','أغلق وتعلّم'] : ['Capture the signal','Understand intent','Assign ownership','Follow up on time','Close and learn']
  const descs = locale === 'ar' ? ['رسالة تصل من أي قناة، بلا نسخ ولصق','يفهم النظام: استفسار؟ طلب؟ شكوى؟','لكل محادثة صاحب وموعد استجابة','تذكير وقالب رد قبل أن يبرد العميل','النتيجة تتحول إلى بيانات تحسّن ما بعدها'] : ['A message arrives from any channel—no copy-paste','The system reads intent: question, order, complaint','Every thread gets an owner and response window','A reminder and reply draft before the lead goes cold','The outcome becomes data for the next round']
  return <div className={`workflow ${compact ? 'compact' : ''}`}>{steps.map((step, i) => <div className="workflow-step" key={step}><span className="step-number">0{i + 1}</span><span>{step}</span>{!compact && <small className="step-desc">{descs[i]}</small>}{i < steps.length - 1 && <span className="step-line"/>}</div>)}</div>
}

function SectionIntro({ kicker, title, body, align = 'center' }) { return <Reveal className={`section-intro align-${align}`}><span className="kicker">{kicker}</span><h2>{title}</h2>{body && <p>{body}</p>}</Reveal> }

const features = [
  { icon: MessageCircle, title: c('محادثة لا تضيع', 'No conversation gets lost'), body: c('واتساب وماسنجر وإنستغرام في صندوق واحد. لكل محادثة مالك وموعد رد وخطوة تالية، فلا رسالة تنام بلا رد.', 'WhatsApp, Messenger, and Instagram in one inbox. Every thread has an owner, a response window, and a next step—so nothing sits unanswered.') },
  { icon: Database, title: c('سياق يسبق السؤال', 'Context before the question'), body: c('قبل أن يرد المندوب يرى من هو العميل، وماذا طلب آخر مرة، وأين وصل طلبه — بدل سؤاله من جديد.', 'Before a rep replies, they see who the customer is, what they last asked, and where their order stands—no more asking twice.') },
  { icon: Zap, title: c('متابعة تعمل بوضوح', 'Follow-up with clarity'), body: c('اكتب قاعدة مثل: لم يرد العميل خلال 24 ساعة ← أنشئ مهمة متابعة. كل قاعدة مرئية وقابلة للإيقاف.', 'Write a rule like: no reply in 24 hours → create a follow-up task. Every rule is visible and can be paused.') },
]

function FeatureGrid({ locale }) { return <div className="feature-grid">{features.map(({icon: Icon, title, body}) => <Reveal className="reveal-cell" key={title.ar}><article className="feature-card"><span className="icon-tile"><Icon size={20}/></span><h3>{tx(title, locale)}</h3><p>{tx(body, locale)}</p><a href="/product">{tx(c('استكشف القدرة','Explore capability'), locale)} <ArrowRight size={15}/></a></article></Reveal>)}</div> }

function DemoProof({ locale }) { return <section className="section section-proof"><div className="container proof-grid"><div><DemoBadge locale={locale}/><h2>{tx(c('لا نبيعك شاشة. نريك مسار العمل.', 'We do not sell you a screen. We show you the path.'), locale)}</h2><p>{tx(c('كل مثال في هذه النسخة تجريبي وموسوم بوضوح. عندما تتوفر بيانات حقيقية، سنعرض مصدرها وفترتها وسياقها.', 'Every example in this build is illustrative and clearly labeled. When real data exists, we will show its source, period, and context.'), locale)}</p><Button href="/conversations" kind="secondary">{tx(c('شاهد داخل المنتج','See inside the product'), locale)}</Button></div><ProductFrame locale={locale} variant="assistant"/></div></section> }

function Home({ locale }) { return <><section className="hero"><div className="hero-bg-canvas"><HeroRelationCanvas/></div><div className="container hero-grid"><div className="hero-copy"><span className="eyebrow"><span/> FIHRIST</span><KineticHeadline locale={locale}/><p className="hero-lede">{tx(c('رسائل واتساب وماسنجر وإنستغرام تصل إلى صندوق واحد. FIHRIST يعرّف العميل، يستخرج طلبه، ويقترح الرد والخطوة التالية — وفريقك يعتمد.', 'WhatsApp, Messenger, and Instagram messages land in one inbox. FIHRIST identifies the customer, extracts the request, and suggests the reply and next step — your team approves.'), locale)}</p><div className="hero-actions"><Button href="/register">{tx(c('ابدأ الآن','Start now'), locale)}</Button><Button href="/contact-sales" kind="secondary">{tx(c('احجز Demo','Book a demo'), locale)}</Button></div><ChannelChips locale={locale}/><div className="hero-note"><ShieldCheck size={16}/><span>{tx(c('محتوى تجريبي · لا توجد تكاملات إنتاجية', 'Demo content · no production integrations'), locale)}</span></div></div><div className="hero-visual"><span className="hero-visual-label"><span className="demo-dot"/>{tx(c('شبكة العلاقات · تفاعلي', 'Relation network · interactive'), locale)}</span></div></div></section><section className="section section-workflow"><div className="container"><SectionIntro kicker={tx(c('السرد في سطر واحد','The story in one line'), locale)} title={tx(c('من رسالة عابرة إلى خطوة يملكها شخص.', 'From a passing message to an owned next action.'), locale)} body={tx(c('من أول سؤال إلى آخر متابعة، يحافظ FIHRIST على الخيط الذي يجعل المبيعات قابلة للفهم.', 'From the first question to the last follow-up, FIHRIST keeps the thread that makes sales understandable.'), locale)}/><Workflow locale={locale}/><div className="workflow-caption"><span className="caption-line"/><span>{tx(c('محادثة → عميل → طلب → خطوة تالية', 'Conversation → customer → request → next action'), locale)}</span><span className="caption-line"/></div></div></section><BeforeAfter locale={locale}/><section className="section section-features"><div className="container"><SectionIntro kicker={tx(c('المنصة','The platform'), locale)} title={tx(c('لا تجمع أدوات. اجمع قرارات.', 'Stop collecting tools. Start collecting decisions.'), locale)} body={tx(c('ثلاث قدرات تعمل معًا: صندوق واحد، سياق كامل، ومتابعة لا تنسى.', 'Three capabilities that work together: one inbox, full context, follow-up that never forgets.'), locale)}/><FeatureGrid locale={locale}/></div></section><ScenarioDemo locale={locale}/><DemoProof locale={locale}/><section className="section section-audience"><div className="container"><SectionIntro kicker={tx(c('مسارات مختلفة، أساس واحد','Different paths, one foundation'), locale)} title={tx(c('ابدأ من المشكلة التي تراها كل يوم.', 'Start with the problem you see every day.'), locale)}/><div className="audience-grid"><AudienceCard icon={Users} title={c('فرق المبيعات','Sales teams')} body={c('منع ضياع الفرص، وتحديد الخطوة التالية لكل مندوب.', 'Keep opportunities visible and the next action clear for every rep.')} href="/conversations" locale={locale}/><AudienceCard icon={Layers3} title={c('المديرون والمالكون','Leaders & owners')} body={c('رؤية ما يتحرك وما يتعطل قبل اجتماع التنبؤ.', 'See what is moving and what is stuck before the forecast meeting.')} href="/context" locale={locale}/><AudienceCard icon={Network} title={c('العمليات والمؤسسات','Operations & enterprise')} body={c('حوكمة، صلاحيات، وتكاملات يمكن مراجعتها والتوسع بها.', 'Governance, permissions, and integrations you can review and scale.')} href="/security" locale={locale}/></div></div></section><Faq locale={locale}/></> }
function AudienceCard({icon: Icon, title, body, href, locale}) { return <Reveal className="reveal-cell"><a className="audience-card" href={href}><span className="icon-tile"><Icon size={20}/></span><h3>{tx(title, locale)}</h3><p>{tx(body, locale)}</p><span className="card-arrow"><ArrowRight size={17}/></span></a></Reveal> }

function App() { const [locale, setLocale] = useState(() => { try { const saved = window.localStorage.getItem('fh_locale'); return saved === 'en' ? 'en' : 'ar' } catch { return 'ar' } }); const [theme, setTheme] = useState(() => { try { const saved = window.localStorage.getItem('fh_theme'); if (saved === 'dark' || saved === 'light') return saved; return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch { return 'light' } }); const [page, setPage] = useState(pageFromPath()); useEffect(() => { const onPop = () => setPage(pageFromPath()); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, []); useEffect(() => { document.documentElement.lang = locale; document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'; try { window.localStorage.setItem('fh_locale', locale); window.localStorage.setItem('fh_theme', theme) } catch {} document.title = tx(pageMeta[page], locale); const desc = document.querySelector('meta[name="description"]'); if (desc) desc.setAttribute('content', tx(c('FIHRIST — نظام تشغيل مبيعات عربي-first يربط المحادثات بالعملاء والطلبات والمتابعة.', 'FIHRIST — an Arabic-first sales operating system connecting conversations, customers, requests, and follow-up.'), locale)) }, [locale, theme, page]); const pageComponents = { product: Product, conversations: Conversations, context: Context, assistant: Assistant, automation: Automation, pricing: Pricing, security: Security, privacy: Privacy, terms: Terms, 'contact-sales': ContactSales, support: Support }
  const PageComponent = pageComponents[page]
  const content = useMemo(() => page === 'home' || !PageComponent ? <Home locale={locale}/> : <PageComponent locale={locale}/>, [locale, page, PageComponent]); return <div className={`app ${theme === 'dark' ? 'theme-dark' : ''}`} data-theme={theme} data-lang={locale}><InteractiveBackground/><Spotlight/><Header locale={locale} setLocale={setLocale} theme={theme} toggleTheme={() => setTheme((value) => value === 'light' ? 'dark' : 'light')}/><main className="route-shell" key={`${page}-${locale}`}>{content}</main><footer className="site-footer"><div className="container footer-center"><div className="footer-brand-large"><img src="/fihrist-mark.svg" alt="" /><span>FIHRIST</span></div><p className="footer-tagline">{tx(c('نظام تشغيل مبيعات عربي-first، مبني حول الخطوة التالية.', 'An Arabic-first sales operating system built around the next action.'), locale)}</p><nav className="footer-nav-links"><a href="/product">{tx(c('المنصة','Platform'), locale)}</a><a href="/conversations">{tx(c('المحادثات','Conversations'), locale)}</a><a href="/automation">{tx(c('الأتمتة','Automation'), locale)}</a><a href="/security">{tx(c('الأمان','Security'), locale)}</a><a href="/privacy">{tx(c('الخصوصية','Privacy'), locale)}</a><a href="/terms">{tx(c('الشروط','Terms'), locale)}</a><a href="/support">{tx(c('الدعم','Support'), locale)}</a><a href="/contact-sales">{tx(c('المبيعات','Sales'), locale)}</a></nav><div className="footer-bottom"><span>© 2026 FIHRIST / V2 prototype</span><span>{tx(c('بيانات تجريبية فقط · لا توجد تكاملات إنتاجية', 'Demo data only · no production integrations'), locale)}</span></div></div></footer></div> }

function ChannelChips({ locale }) {
  return <div className="channel-chips"><span>{tx(c('القنوات','Channels'), locale)}</span>{['WhatsApp','Messenger','Instagram','Email','Web chat'].map((n) => <b key={n}><i/>{n}</b>)}</div>
}

function BeforeAfter({ locale }) {
  const messy = [[24,30,150,-6],[150,96,170,5],[30,160,140,-3],[200,178,130,6],[236,26,120,4]]
  return <section className="section section-ba"><div className="container">
    <SectionIntro kicker={tx(c('قبل وبعد','Before & after'), locale)} title={tx(c('الفرق بين رسالة ضاعت وصفقة أُغلقت.', 'The gap between a lost message and a closed deal.'), locale)}/>
    <div className="ba-grid">
      <figure className="ba-card"><svg viewBox="0 0 400 230" role="img" aria-label={tx(c('رسائل مبعثرة','Scattered messages'), locale)}>{messy.map(([x,y,w,r],i) => <g key={i} transform={`rotate(${r} ${x+w/2} ${y+18})`}><rect x={x} y={y} width={w} height="36" rx="8" className="ba-bubble"/><rect x={x+12} y={y+10} width={w*0.6} height="5" rx="2.5" className="ba-line"/><rect x={x+12} y={y+21} width={w*0.35} height="5" rx="2.5" className="ba-line"/></g>)}{[[366,70],[110,214],[330,140]].map(([x,y],i) => <g key={i}><circle cx={x} cy={y} r="13" className="ba-warn"/><text x={x} y={y+5} textAnchor="middle" className="ba-q">?</text></g>)}</svg>
        <figcaption><b>{tx(c('بدون نظام','Without a system'), locale)}</b><span>{tx(c('كل قناة في تطبيق، لا مالك للمحادثة، ولا أحد يعرف من ردّ على من.','Every channel in a different app, no owner, and nobody knows who replied to whom.'), locale)}</span></figcaption></figure>
      <figure className="ba-card ba-after"><svg viewBox="0 0 400 230" role="img" aria-label={tx(c('مسار منظم','An organized path'), locale)}>{[0,1,2].map((i) => <g key={i} transform={`translate(20 ${22+i*68})`}><circle cx="18" cy="18" r="16" className="ba-avatar"/><rect x="48" y="2" width="120" height="32" rx="8" className="ba-bubble"/><path d="M176 18h56" className="ba-arrow"/><rect x="240" y="2" width="90" height="32" rx="8" className="ba-chip"/><circle cx="356" cy="18" r="11" className="ba-ok"/><path d="M351 18l4 4 7-8" className="ba-tick"/></g>)}</svg>
        <figcaption><b>{tx(c('مع FIHRIST','With FIHRIST'), locale)}</b><span>{tx(c('رسالة ← عميل ← طلب ← مالك ← خطوة تالية. كل شيء في مكانه.','Message → customer → request → owner → next step. Everything in its place.'), locale)}</span></figcaption></figure>
    </div></div></section>
}

function ScenarioDemo({ locale }) {
  const [tab, setTab] = useState(0)
  const [ok, setOk] = useState(false)
  const items = [
    { tab: c('متجر إلكتروني','Online store'), ch: 'WhatsApp', msg: c('عندكم الفستان الأسود مقاس M؟ وهل أستلمه غدًا؟','Do you have the black dress in size M? Can I get it tomorrow?'), f: [[c('النية','Intent'), c('توفر + توصيل','Availability + delivery')],[c('المنتج','Product'), c('فستان أسود · M','Black dress · M')],[c('الأولوية','Priority'), c('عالية','High')]], reply: c('أهلًا! المقاس M متوفر ✅ والتوصيل غدًا إذا أكدت الطلب قبل 6 مساءً. أرسل لك الصورة والسعر؟','Hi! Size M is in stock ✅ Delivery tomorrow if you confirm before 6 PM. Want the photo and price?'), next: c('أنشئ طلبًا وذكّر بعد 24 ساعة','Create an order and remind in 24h') },
    { tab: c('عيادة','Clinic'), ch: 'Messenger', msg: c('أريد موعد تنظيف أسنان الأسبوع القادم، يفضّل مساءً.','I need a teeth-cleaning appointment next week, preferably evening.'), f: [[c('النية','Intent'), c('حجز موعد','Book appointment')],[c('الخدمة','Service'), c('تنظيف أسنان','Teeth cleaning')],[c('الوقت','Time'), c('الأسبوع القادم · مساءً','Next week · evening')]], reply: c('يسعدنا خدمتك! المتاح الأحد 6:30 م أو الثلاثاء 7:00 م. أيهما يناسبك؟','Happy to help! We have Sunday 6:30 PM or Tuesday 7:00 PM. Which works?'), next: c('احجز الموعد وأرسل تأكيدًا','Book the slot and send a confirmation') },
    { tab: c('شركة خدمات','B2B services'), ch: 'Email', msg: c('نحتاج عرض سعر لـ 20 مستخدمًا مع تدريب، وقرارنا نهاية الشهر.','We need a quote for 20 users with training; we decide by month-end.'), f: [[c('النية','Intent'), c('طلب عرض سعر','Quote request')],[c('الحجم','Size'), c('20 مستخدمًا','20 users')],[c('الموعد','Deadline'), c('نهاية الشهر','Month-end')]], reply: c('بكل سرور. نجهز لكم عرضًا يشمل التدريب ونرسله خلال يومين عمل. من صاحب القرار لديكم؟','Gladly. We will prepare a quote including training within two business days. Who is the decision maker?'), next: c('عيّن مندوبًا وحدد متابعة قبل الموعد','Assign a rep and schedule a follow-up before the deadline') },
  ]
  const s = items[tab]
  const steps = [
    [c('العميل يكتب','Customer writes'), <div className="scn-bubble"><small>{s.ch}</small>{tx(s.msg, locale)}</div>],
    [c('النظام يفهم','System understands'), <dl>{s.f.map(([k, v]) => <div key={k.en}><dt>{tx(k, locale)}</dt><dd>{tx(v, locale)}</dd></div>)}</dl>],
    [c('AI يقترح الرد','AI drafts the reply'), <><div className="scn-bubble ai"><small>AI</small>{tx(s.reply, locale)}</div><div className="scn-actions"><button className={ok ? 'is-approved' : ''} onClick={() => setOk(true)}><Check size={14}/> {ok ? tx(c('تم الاعتماد','Approved'), locale) : tx(c('اعتماد وإرسال','Approve & send'), locale)}</button><button className="muted">{tx(c('تعديل','Edit'), locale)}</button></div></>],
    [c('الخطوة التالية','Next step'), <><p>{tx(s.next, locale)}</p><span className="tag teal">{ok ? tx(c('مجدولة','Scheduled'), locale) : tx(c('بانتظار الاعتماد','Awaiting approval'), locale)}</span></>],
  ]
  return <section className="section section-scenario"><div className="container">
    <SectionIntro kicker={tx(c('مثال حي','Live example'), locale)} title={tx(c('جرّب رسالة واحدة من أولها لآخرها.', 'Follow one message from start to finish.'), locale)} body={tx(c('اختر نوع نشاطك وشاهد ماذا يحدث بعد أن يكتب العميل.', 'Pick a business type and see what happens after a customer writes.'), locale)}/>
    <div className="scn-tabs" role="tablist">{items.map((it, i) => <button key={it.ch} role="tab" aria-selected={i === tab} className={i === tab ? 'active' : ''} onClick={() => { setTab(i); setOk(false) }}>{tx(it.tab, locale)}</button>)}</div>
    <div className="scn-grid">{steps.map(([t, body], i) => <Reveal className="reveal-cell" key={i}><article className="scn-step"><span className="scn-num">0{i + 1}</span><h3>{tx(t, locale)}</h3>{body}</article></Reveal>)}</div>
    <div className="scn-note"><DemoBadge locale={locale}/></div></div></section>
}

function Faq({ locale }) {
  const qa = [
    [c('هل يرد AI على عملائي وحده؟','Does AI reply to my customers on its own?'), c('لا. AI يقترح الرد ويلخّص المحادثة، وفريقك يعتمد أو يعدّل أو يرفض. الاعتماد البشري هو الأساس.','No. AI suggests the reply and summarizes the thread; your team approves, edits, or rejects. Human approval is the default.')],
    [c('ما القنوات المستهدفة؟','Which channels are supported?'), c('WhatsApp وMessenger وInstagram والبريد وشات الموقع. حالة كل تكامل تظهر بوضوح داخل المنتج.','WhatsApp, Messenger, Instagram, email, and web chat. The status of each integration is shown clearly in the product.')],
    [c('هل يفهم رسائل العملاء بالعربية؟','Does it understand Arabic messages?'), c('نصممه عربيًا أولًا، ليتعامل مع الرسائل التي تخلط الفصحى واللهجة والإنجليزية كما يكتبها العملاء فعلًا.','It is designed Arabic-first, for messages that mix formal Arabic, dialect, and English the way customers actually write.')],
    [c('أين تُحفظ بياناتي ومن يراها؟','Where is my data kept and who can see it?'), c('لكل معلومة مصدر ووقت تحديث، مع صلاحيات وسجل نشاط. التفاصيل في صفحة الأمان.','Every detail has a source and freshness, with permissions and an activity trail. See the Security page for details.')],
    [c('من أين أبدأ؟','Where do I start?'), c('من مسار واحد فقط، مثل متابعة عروض الأسعار. ثم توسّع تدريجيًا حين تثق بالنتيجة.','With a single path, such as quote follow-up. Then expand gradually once you trust the results.')],
  ]
  return <section className="section section-faq"><div className="container faq-wrap">
    <SectionIntro kicker={tx(c('أسئلة شائعة','FAQ'), locale)} title={tx(c('قبل أن تسأل.', 'Before you ask.'), locale)}/>
    {qa.map(([q, a]) => <details className="faq-item" key={q.en}><summary><span>{tx(q, locale)}</span></summary><p>{tx(a, locale)}</p></details>)}
  </div></section>
}

function FixedLayoutDirection() {
  useEffect(() => {
    const root = document.documentElement
    root.dir = 'ltr'
    const observer = new MutationObserver(() => {
      if (root.dir !== 'ltr') root.dir = 'ltr'
    })
    observer.observe(root, { attributes: true, attributeFilter: ['dir'] })
    return () => observer.disconnect()
  }, [])
  return null
}

function Fihrist() {
  return <><FixedLayoutDirection /><App /></>
}

export default Fihrist
