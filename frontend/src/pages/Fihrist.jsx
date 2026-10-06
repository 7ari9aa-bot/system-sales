import React, { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Check, Database, Globe2, Inbox, Layers3, Menu, MessageCircle, Moon, Network, Search, ShieldCheck,
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
  home: c('FIHRIST — نظام تشغيل المبيعات للمتاجر', 'FIHRIST — Sales Operating System for stores'),
  product: c('FIHRIST — المنصة التي تربط دورة البيع', 'FIHRIST — The connected sales platform'),
  conversations: c('FIHRIST — محادثات العملاء وسياق البيع', 'FIHRIST — Customer conversations and sales context'),
  context: c('FIHRIST — سياق العميل ومسار البيع', 'FIHRIST — Customer context across the sale'),
  assistant: c('FIHRIST — مساعد العملاء ومساعد تحليل المبيعات', 'FIHRIST — Customer and sales-analysis AI'),
  automation: c('FIHRIST — المتابعة والقواعد', 'FIHRIST — Follow-up and business rules'),
  pricing: c('FIHRIST — الخطط والأسعار', 'FIHRIST — Plans and pricing'),
  security: c('FIHRIST — الأمان والتحكم في الوصول', 'FIHRIST — Security and access control'),
  privacy: c('سياسة الخصوصية', 'Privacy policy'),
  terms: c('شروط الاستخدام', 'Terms of use'),
  'contact-sales': c('FIHRIST — تواصل مع المبيعات', 'FIHRIST — Contact sales'),
  support: c('ابدأ من هنا', 'Start here'),
}

const pageDescriptions = {
  home: c('FIHRIST يربط محادثات العملاء بالمنتجات والطلبات والمبيعات والمخزون، مع أدوات للمتابعة وقراءة أداء المتجر.', 'FIHRIST connects customer conversations with products, orders, sales, and inventory, with tools for follow-up and store insights.'),
  product: c('منصة مبيعات تربط المحادثات والمنتجات والطلبات والمبيعات والمخزون والمتابعة في دورة واحدة.', 'A sales platform connecting conversations, products, orders, sales, inventory, and follow-up in one workflow.'),
  conversations: c('اجمع محادثات WhatsApp وMessenger وInstagram والبريد وشات الموقع مع سياق العميل والمنتج والطلب.', 'Connect WhatsApp, Messenger, Instagram, email, and web chat with customer, product, and order context.'),
  context: c('اربط سياق العميل بالمنتج والطلب والبيع والمخزون حتى يعرف الفريق ما حدث وما الخطوة التالية.', 'Carry customer context through products, orders, sales, and inventory so your team can see what happened and what comes next.'),
  assistant: c('مساعد عملاء يجيب تلقائيًا عند تفعيله، ومساعد تحليل مبيعات يساعد التاجر على فهم بيانات المتجر.', 'A customer assistant that answers automatically when enabled, plus a sales-analysis assistant that helps merchants understand store data.'),
  automation: c('نظّم التذكيرات وقواعد المتابعة داخل FIHRIST حتى تظل الخطوة التالية واضحة.', 'Organize reminders and follow-up rules inside FIHRIST so the next step stays clear.'),
  pricing: c('تعرّف على خيارات خطط FIHRIST والأسعار المتاحة عبر فريق المبيعات.', 'Explore FIHRIST plan options and current pricing with the sales team.'),
  security: c('تعرف على كيفية تنظيم الوصول وصلاحيات الفريق ودور المراجعة والتدخل البشري داخل FIHRIST.', 'See how FIHRIST organizes access, team permissions, and human review and intervention.'),
  'contact-sales': c('استكشف FIHRIST وما يمكن أن يناسب دورة البيع والمحادثات والطلبات والمخزون في متجرك.', 'Explore FIHRIST and the options that may fit your store\'s conversations, orders, sales, and inventory workflow.'),
  support: c('إرشادات عملية لمتابعة المحادثات والمنتجات والطلبات والخطوة التالية داخل FIHRIST.', 'Practical guidance for conversations, products, orders, and the next step in FIHRIST.'),
}

function KineticHeadline({ locale }) {
  const words = locale === 'ar' ? ['البيع.'] : ['sale.']
  const [index, setIndex] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => setIndex((value) => (value + 1) % words.length), 2600); return () => window.clearInterval(timer) }, [words.length])
  return <h1>{tx(c('من محادثة العميل إلى', 'From customer conversation to'), locale)} <span className="kinetic-slot">{words.map((w, i) => <span key={w} className={i === index ? 'kinetic-word on' : 'kinetic-word'} aria-hidden={i !== index}>{w}</span>)}</span><br/>{tx(c('في مسار واحد.', 'in one connected journey.'), locale)}</h1>
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

function DemoBadge({ locale = 'ar' }) { return <span className="demo-badge"><span className="demo-dot" /> {tx(c('معاينة توضيحية', 'Illustrative preview'), locale)}</span> }

function ProductFrame({ variant = 'inbox', locale }) {
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
  useEffect(() => { if (variant !== 'inbox') return; const timer = window.setInterval(() => setActiveThread((value) => (value + 1) % threadData.length), 4500); return () => window.clearInterval(timer) }, [variant, threadData.length])
  const visibleThreads = filter === 'all' ? threadData : filter === 'priority' ? threadData.slice(0, 2) : threadData.slice(1)
  const active = threadData[activeThread] || threadData[0]
  return <div className={`product-frame product-${variant}`} dir="ltr" aria-label={isAr ? 'لقطة تجريبية من واجهة FIHRIST' : 'Illustrative FIHRIST product interface'}>
    <div className="product-topbar"><div className="window-dots"><i/><i/><i/></div><span className="product-url">FIHRIST / {variant}</span><span className="product-live"><span/> Preview</span></div>
    <div className="product-body">
      <aside className="product-rail"><div className="rail-mark">F</div><Inbox size={17}/><Users size={17}/><Target size={17}/><WorkflowIcon size={17}/><SettingsIcon /></aside>
      <div className="product-main" dir="ltr">
        <div className="product-heading"><div><span className="eyebrow-mini">{variant === 'inbox' ? 'INBOX / TODAY' : variant.toUpperCase()}</span><h3>{variant === 'inbox' ? (isAr ? 'المحادثات المهمة اليوم' : 'Priority conversations') : variant === 'assistant' ? (isAr ? 'اقتراحات المساعد' : 'Assistant suggestions') : variant === 'automation' ? (isAr ? 'متابعة العميل' : 'Customer follow-up') : (isAr ? 'سجل العميل' : 'Customer record')}</h3></div><span className="avatar">أ</span></div>
        {variant === 'inbox' && <><div className="demo-toolbar"><div className="demo-search"><Search size={13}/><span>{isAr ? 'ابحث في المحادثات...' : 'Search conversations...'}</span></div><div className="demo-tabs">{[['all', isAr ? 'الكل' : 'All'], ['priority', isAr ? 'مهم' : 'Priority'], ['unread', isAr ? 'غير مقروء' : 'Unread']].map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => { setFilter(key); setActiveThread(0) }}>{label}</button>)}</div><button className="demo-filter" aria-label={isAr ? 'تصفية' : 'Filter'}><SlidersHorizontal size={13}/></button></div><div className="inbox-layout"><div className="thread-list">{visibleThreads.map(([name, preview], visibleIndex) => { const i = filter === 'unread' ? visibleIndex + 1 : visibleIndex; return ( <button className={`thread ${i === activeThread ? 'active' : ''}`} key={name} onClick={() => setActiveThread(i)} aria-pressed={i === activeThread}><span className={`thread-avatar ${i === 1 ? 'gray' : i === 2 ? 'sand' : ''}`}>{name[0]}</span><span><b>{name}</b><small>{preview}</small></span><em>{i === activeThread ? (isAr ? 'الآن' : 'now') : `${i + 1}${isAr ? 'س' : 'h'}`}</em></button>)})}</div><div className="conversation"><div className="bubble customer">{active[1]}<small>10:42</small></div><div className="bubble ai"><Sparkles size={13}/>{isAr ? `سؤال العميل: ${active[2]} + خطوة تالية مقترحة` : `Customer request: ${active[2]} + suggested next step`}<small>{isAr ? 'مساعدة AI' : 'AI assistance'}</small></div><div className="conversation-footer"><span className="tag teal">{active[2]}</span><span className="tag">{isAr ? 'التالي: أرسل تفاصيل المنتج المتاحة' : 'Next: send the available product details'}</span></div></div></div></>}
         {variant !== 'inbox' && <div className="detail-layout"><div className="detail-card"><div className="detail-line"><span className="detail-icon teal"><Sparkles size={15}/></span><span><b>{variant === 'assistant' ? (isAr ? 'ملخص المحادثة' : 'Conversation summary') : variant === 'automation' ? (isAr ? 'الخطوة التالية' : 'Next action') : (isAr ? 'سياق موثوق' : 'Trusted context')}</b><small>{variant === 'assistant' ? (isAr ? 'العميل يسأل عن المقاس والتوفر.' : 'Customer asks about size and availability.') : variant === 'automation' ? (isAr ? 'أنشئ مهمة متابعة عند الحاجة.' : 'Create a follow-up task when needed.') : (isAr ? 'آخر طلب، المالك، ومصدر البيانات.' : 'Last order, owner, and data source.')}</small></span></div><div className="detail-line"><span className="detail-icon sand"><Database size={15}/></span><span><b>{isAr ? 'المصدر' : 'Source'}</b><small>{isAr ? 'محادثة العميل · متاحة للفريق' : 'Customer conversation · available to your team'}</small></span></div><div className="detail-actions"><button onClick={() => setApproved(true)} className={approved ? 'is-approved' : ''}><Check size={14}/> {approved ? (isAr ? 'تمت المراجعة' : 'Reviewed') : (isAr ? 'مراجعة المحادثة' : 'Review conversation')}</button><button className="muted">{isAr ? 'تعديل' : 'Edit'}</button></div></div><div className="score-card"><span className="score-label">{isAr ? 'سياق البيع' : 'Sales context'}</span><strong>{isAr ? 'مرتبط' : 'Linked'}</strong><div className="score-bar"><i/></div><small>{isAr ? 'محادثة · منتج · طلب' : 'Conversation · product · order'}</small></div></div>}
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

function Workflow({ locale, compact = false }) {
  const steps = locale === 'ar' ? ['ابدأ من سؤال العميل','اربط العميل بالمنتج','سجّل الطلب والبيع','حدّث المخزون بما بيع وما بقي','تابع الخطوة التالية واقرأ الأداء'] : ['Start with a customer question','Connect the customer and product','Record the order and sale','Update inventory with what sold and what remains','Follow up and review performance']
  const descs = locale === 'ar' ? ['رسالة من إحدى قنوات التواصل المدعومة','سجل العميل وتفاصيل المنتج المتاحة أمام الفريق','اربط الطلب بالمحادثة وسجّل المنتج والاختيار والكمية التي بيعت','تعرّف على ما بيع وما بقي في المخزون','استخدم تذكيرًا أو قاعدة متابعة؛ وتساعد بيانات المتجر على قراءة الأداء'] : ['A message arrives through a supported channel','Customer context and available product details are at hand','Connect the order to the conversation and record the product, option, and quantity sold','See what sold and what remains in inventory','Use a reminder or follow-up rule; store data also supports performance insights']
  return <div className={`workflow ${compact ? 'compact' : ''}`}>{steps.map((step, i) => <div className="workflow-step" key={step}><span className="step-number">0{i + 1}</span><span>{step}</span>{!compact && <small className="step-desc">{descs[i]}</small>}{i < steps.length - 1 && <span className="step-line"/>}</div>)}</div>
}

function SectionIntro({ kicker, title, body, align = 'center' }) { return <Reveal className={`section-intro align-${align}`}><span className="kicker">{kicker}</span><h2>{title}</h2>{body && <p>{body}</p>}</Reveal> }

const features = [
  { icon: MessageCircle, title: c('محادثات العملاء والسياق', 'Customer conversations and context'), body: c('اجمع رسائل WhatsApp وMessenger وInstagram والبريد وشات الموقع مع سجل العميل. عند تفعيله، يجيب مساعد العملاء تلقائيًا عن الأسئلة استنادًا إلى بيانات المتجر، ويستطيع الفريق متابعة المحادثة والتدخل عند الحاجة.', 'Bring WhatsApp, Messenger, Instagram, email, and web chat together with customer context. When enabled, the customer assistant answers questions automatically using store data, and your team can follow the conversation and step in when needed.') },
  { icon: Database, title: c('المنتج والطلب والمخزون', 'Products, orders, and stock'), body: c('اربط السعر والصورة والاختيارات بالطلب، وسجّل الكمية التي بيعت من كل اختيار لتعرف ما بقي. يعرّف رمز QR الصنف ويربطه بتسجيل البيع وحركة المخزون، مع صلاحيات للفريق.', 'Connect prices, images, and options to orders, and record what sold from each option to see what remains. QR codes identify each item and link it to its sales and inventory records, with team permissions.') },
  { icon: Zap, title: c('متابعة وتحليل للمبيعات', 'Follow-up and sales analysis'), body: c('تغذي بيانات الطلبات والمبيعات والمخزون قراءة أداء المتجر. قارن الفترات وحركة المنتجات ونتائج القنوات، ونظّم المتابعة داخل FIHRIST، بينما يساعد مساعد تحليل المبيعات على شرح ما تدعمه البيانات.', 'Orders, sales, and inventory records inform the view of store performance. Compare periods, product movement, and channel results, organize follow-up within FIHRIST, and let the sales-analysis assistant explain what the data supports.') },
]

function FeatureGrid({ locale }) { return <div className="feature-grid">{features.map(({icon: Icon, title, body}) => <Reveal className="reveal-cell" key={title.ar}><article className="feature-card"><span className="icon-tile"><Icon size={20}/></span><h3>{tx(title, locale)}</h3><p>{tx(body, locale)}</p><a href="/product">{tx(c('استكشف القدرة','Explore capability'), locale)} <ArrowRight size={15}/></a></article></Reveal>)}</div> }

function DemoProof({ locale }) { return <section className="section section-proof"><div className="container proof-grid"><div><DemoBadge locale={locale}/><h2>{tx(c('كل خطوة تحمل ما تحتاجه الخطوة التالية.', 'Each step carries what the next one needs.'), locale)}</h2><p>{tx(c('تنتقل بيانات المحادثة والمنتج والطلب إلى سجل البيع والمخزون، وتمنح التاجر أساسًا أوضح لقراءة الأداء والمتابعة.', 'Conversation, product, and order details carry into sales and inventory records, giving merchants a clearer basis for performance insight and follow-up.'), locale)}</p><Button href="/product" kind="secondary">{tx(c('استكشف المنصة','Explore the platform'), locale)}</Button></div><ProductFrame locale={locale} variant="assistant"/></div></section> }

function Home({ locale }) { return <><section className="hero"><div className="hero-bg-canvas"><HeroRelationCanvas/></div><div className="container hero-grid"><div className="hero-copy"><span className="eyebrow"><span/> FIHRIST</span><KineticHeadline locale={locale}/><p className="hero-lede">{tx(c('FIHRIST يربط محادثات العملاء بالمنتجات والطلبات والمبيعات والمخزون. عند تفعيله، يجيب مساعد العملاء تلقائيًا عن الأسئلة اعتمادًا على بيانات المتجر، ويساعد مساعد تحليل المبيعات التاجر على قراءة الأداء.', 'FIHRIST connects customer conversations with products, orders, sales, and inventory. When enabled, the customer assistant automatically answers questions using store data, while the merchant sales-analysis assistant helps review performance.'), locale)}</p><div className="hero-actions"><Button href="/register">{tx(c('ابدأ الآن','Start now'), locale)}</Button><Button href="/contact-sales" kind="secondary">{tx(c('تحدث مع فريقنا','Talk to our team'), locale)}</Button></div><ChannelChips locale={locale}/><div className="hero-note"><ShieldCheck size={16}/><span>{tx(c('تنتقل المعلومات من محادثة العميل إلى الطلب والبيع والمخزون والمتابعة.', 'Information carries from the customer conversation through the order and sale to inventory and follow-up.'), locale)}</span></div></div><div className="hero-visual"><span className="hero-visual-label"><span className="demo-dot"/>{tx(c('مسار البيع مترابط', 'A connected sales journey'), locale)}</span></div></div></section><section className="section section-workflow"><div className="container"><SectionIntro kicker={tx(c('السرد في سطر واحد','The story in one line'), locale)} title={tx(c('من سؤال العميل إلى متابعة المتجر.', 'From a customer question to store follow-up.'), locale)} body={tx(c('تنتقل معلومات العميل والمنتج والطلب إلى البيع والمخزون، ثم تساعدك على قراءة ما حدث وتحديد المتابعة.', 'Customer, product, and order details carry through to sales and inventory, then help you review what happened and plan follow-up.'), locale)}/><Workflow locale={locale}/><div className="workflow-caption"><span className="caption-line"/><span>{tx(c('عميل → محادثة → منتج → طلب → بيع → مخزون → متابعة ورؤية', 'Customer → conversation → product → order → sale → inventory → follow-up and insight'), locale)}</span><span className="caption-line"/></div></div></section><BeforeAfter locale={locale}/><section className="section section-features"><div className="container"><SectionIntro kicker={tx(c('المنصة','The platform'), locale)} title={tx(c('من المحادثة إلى إدارة المتجر.', 'From customer conversation to store operations.'), locale)} body={tx(c('مساعدة للعملاء، تشغيل المنتجات والطلبات والمخزون، وقراءة الأداء والمتابعة.', 'Customer assistance, connected product, order, and inventory operations, and performance insights and follow-up.'), locale)}/><FeatureGrid locale={locale}/></div></section><ScenarioDemo locale={locale}/><DemoProof locale={locale}/><section className="section section-audience"><div className="container"><SectionIntro kicker={tx(c('مسارات مختلفة، أساس واحد','Different paths, one foundation'), locale)} title={tx(c('ابدأ من المشكلة التي تراها كل يوم.', 'Start with the problem you see every day.'), locale)}/><div className="audience-grid"><AudienceCard icon={Users} title={c('فرق المبيعات','Sales teams')} body={c('متابعة محادثات العملاء وربط طلباتهم بالمنتجات والخطوة التالية.', 'Follow customer conversations and connect requests to products and next steps.')} href="/conversations" locale={locale}/><AudienceCard icon={Layers3} title={c('أصحاب المتاجر ومديروها','Store owners and managers')} body={c('تابع المبيعات والطلبات والمخزون، وافهم حركة المنتجات ونتائج قنوات البيع من بيانات المتجر.', 'Track sales, orders, and inventory, and understand product movement and sales-channel performance from your store data.')} href="/product" locale={locale}/><AudienceCard icon={Network} title={c('فرق المتجر والعمليات','Store and operations teams')} body={c('ربط المنتجات والطلبات والمبيعات والمخزون مع صلاحيات تناسب مسؤوليات الفريق.', 'Connect products, orders, sales, and inventory with access suited to team responsibilities.')} href="/security" locale={locale}/></div></div></section><Faq locale={locale}/></> }
function AudienceCard({icon: Icon, title, body, href, locale}) { return <Reveal className="reveal-cell"><a className="audience-card" href={href}><span className="icon-tile"><Icon size={20}/></span><h3>{tx(title, locale)}</h3><p>{tx(body, locale)}</p><span className="card-arrow"><ArrowRight size={17}/></span></a></Reveal> }

function App() { const [locale, setLocale] = useState(() => { try { const saved = window.localStorage.getItem('fh_locale'); return saved === 'en' ? 'en' : 'ar' } catch { return 'ar' } }); const [theme, setTheme] = useState(() => { try { const saved = window.localStorage.getItem('fh_theme'); if (saved === 'dark' || saved === 'light') return saved; return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch { return 'light' } }); const [page, setPage] = useState(pageFromPath()); useEffect(() => { const onPop = () => setPage(pageFromPath()); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, []); useEffect(() => { document.documentElement.lang = locale; document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'; try { window.localStorage.setItem('fh_locale', locale); window.localStorage.setItem('fh_theme', theme) } catch {} document.title = tx(pageMeta[page], locale); const desc = document.querySelector('meta[name="description"]'); if (desc) desc.setAttribute('content', tx(pageDescriptions[page] || c('FIHRIST يربط محادثات العملاء بالمنتجات والطلبات والمبيعات والمخزون، مع أدوات للمتابعة وقراءة أداء المتجر.', 'FIHRIST connects customer conversations with products, orders, sales, and inventory, with tools for follow-up and store insights.'), locale)) }, [locale, theme, page]); const pageComponents = { product: Product, conversations: Conversations, context: Context, assistant: Assistant, automation: Automation, pricing: Pricing, security: Security, privacy: Privacy, terms: Terms, 'contact-sales': ContactSales, support: Support }
  const PageComponent = pageComponents[page]
  const content = useMemo(() => page === 'home' || !PageComponent ? <Home locale={locale}/> : <PageComponent locale={locale}/>, [locale, page, PageComponent]); return <div className={`app ${theme === 'dark' ? 'theme-dark' : ''}`} data-theme={theme} data-lang={locale}><InteractiveBackground/><Spotlight/><Header locale={locale} setLocale={setLocale} theme={theme} toggleTheme={() => setTheme((value) => value === 'light' ? 'dark' : 'light')}/><main className="route-shell" key={page}>{content}</main><footer className="site-footer"><div className="container footer-center"><div className="footer-brand-large"><img src="/fihrist-mark.svg" alt="" /><span>FIHRIST</span></div><p className="footer-tagline">{tx(c('نظام مبيعات يربط المحادثات بالمنتجات والطلبات والمبيعات والمخزون والمتابعة والرؤية.', 'A sales system connecting conversations with products, orders, sales, inventory, follow-up, and insight.'), locale)}</p><nav className="footer-nav-links"><a href="/product">{tx(c('المنصة','Platform'), locale)}</a><a href="/conversations">{tx(c('المحادثات','Conversations'), locale)}</a><a href="/automation">{tx(c('التذكيرات والمتابعة','Reminders & follow-up'), locale)}</a><a href="/security">{tx(c('الأمان','Security'), locale)}</a><a href="/privacy">{tx(c('الخصوصية','Privacy'), locale)}</a><a href="/terms">{tx(c('الشروط','Terms'), locale)}</a><a href="/support">{tx(c('الدعم','Support'), locale)}</a><a href="/contact-sales">{tx(c('المبيعات','Sales'), locale)}</a></nav><div className="footer-bottom"><span>© 2026 FIHRIST</span><span>{tx(c('الواجهة المعروضة مثال توضيحي لمسار العمل.', 'The interface shown is an illustrative view of the workflow.'), locale)}</span></div></div></footer></div> }

function ChannelChips({ locale }) {
  return <div className="channel-chips"><span>{tx(c('القنوات','Channels'), locale)}</span>{['WhatsApp','Messenger','Instagram','Email','Web chat'].map((n) => <b key={n}><i/>{n}</b>)}</div>
}

function BeforeAfter({ locale }) {
  const messy = [[24,30,150,-6],[150,96,170,5],[30,160,140,-3],[200,178,130,6],[236,26,120,4]]
  return <section className="section section-ba"><div className="container">
    <SectionIntro kicker={tx(c('قبل وبعد','Before & after'), locale)} title={tx(c('الفرق بين محادثة منفصلة ومسار بيع واضح.', 'The difference between a disconnected conversation and a clear sales journey.'), locale)}/>
    <div className="ba-grid">
      <figure className="ba-card"><svg viewBox="0 0 400 230" role="img" aria-label={tx(c('رسائل مبعثرة','Scattered messages'), locale)}>{messy.map(([x,y,w,r],i) => <g key={i} transform={`rotate(${r} ${x+w/2} ${y+18})`}><rect x={x} y={y} width={w} height="36" rx="8" className="ba-bubble"/><rect x={x+12} y={y+10} width={w*0.6} height="5" rx="2.5" className="ba-line"/><rect x={x+12} y={y+21} width={w*0.35} height="5" rx="2.5" className="ba-line"/></g>)}{[[366,70],[110,214],[330,140]].map(([x,y],i) => <g key={i}><circle cx={x} cy={y} r="13" className="ba-warn"/><text x={x} y={y+5} textAnchor="middle" className="ba-q">?</text></g>)}</svg>
        <figcaption><b>{tx(c('بدون نظام','Without a system'), locale)}</b><span>{tx(c('المحادثات موزعة بين قنوات مختلفة، وقد تضيع المسؤولية والسياق بين خطوة وأخرى.','Conversations can be spread across channels, making ownership and context harder to follow.'), locale)}</span></figcaption></figure>
      <figure className="ba-card ba-after"><svg viewBox="0 0 400 230" role="img" aria-label={tx(c('مسار منظم','An organized path'), locale)}>{[0,1,2].map((i) => <g key={i} transform={`translate(20 ${22+i*68})`}><circle cx="18" cy="18" r="16" className="ba-avatar"/><rect x="48" y="2" width="120" height="32" rx="8" className="ba-bubble"/><path d="M176 18h56" className="ba-arrow"/><rect x="240" y="2" width="90" height="32" rx="8" className="ba-chip"/><circle cx="356" cy="18" r="11" className="ba-ok"/><path d="M351 18l4 4 7-8" className="ba-tick"/></g>)}</svg>
        <figcaption><b>{tx(c('مع FIHRIST','With FIHRIST'), locale)}</b><span>{tx(c('رسالة ← عميل ← منتج ← طلب ← بيع ← مخزون ← خطوة تالية.','Message → customer → product → order → sale → inventory → next step.'), locale)}</span></figcaption></figure>
    </div></div></section>
}

function ScenarioDemo({ locale }) {
  const [tab, setTab] = useState(0)
  const [ok, setOk] = useState(false)
  const items = [
    { tab: c('السعر والتوفر','Price and availability'), ch: 'WhatsApp', msg: c('هل هذا المنتج متوفر؟ وما سعره؟','Is this product available? What is the price?'), f: [[c('طلب العميل','Customer request'), c('السعر والتوفر','Price and availability')],[c('معلومات المنتج','Product details'), c('السعر والتوفر المسجلان','Listed price and availability')],[c('الخطوة التالية','Next step'), c('مراجعة المعلومات المتاحة','Check available information')]], reply: c('سأتحقق من بيانات المنتج المتاحة وأشاركك السعر والتوفر.','I’ll check the available product details and share the price and availability.'), next: c('سجّل الطلب إذا اختار العميل المنتج','Record an order if the customer chooses the product') },
    { tab: c('العثور على منتج بصورة','Find a product from a photo'), ch: 'Messenger', msg: c('أرسلت صورة. عندكم منتج قريب منها؟','I sent a photo. Do you have something like it?'), f: [[c('طلب العميل','Customer request'), c('صورة أرسلها العميل','Photo shared by the customer')],[c('معلومات المنتج','Product details'), c('منتجات ذات صلة بالصورة وبيانات المنتجات المسجلة','Relevant products based on the shared image and listed product data')],[c('الخطوة التالية','Next step'), c('مراجعة النتائج والتفاصيل المتاحة','Review results and available details')]], reply: c('سأبحث في صور المنتجات المسجلة وأشاركك أقرب الخيارات المتاحة.','I’ll check the product images on record and share the closest available options.'), next: c('راجع تفاصيل المنتج والاختيارات المتاحة','Review product details and available options') },
    { tab: c('الاختيارات المتاحة','Available options'), ch: 'Email', msg: c('ما الاختيارات المتاحة لهذا المنتج؟','What options are available for this product?'), f: [[c('طلب العميل','Customer request'), c('الاختيارات المتاحة','Available options')],[c('معلومات المنتج','Product details'), c('الاختيارات المسجلة للمنتج','Options listed for the product')],[c('الخطوة التالية','Next step'), c('مشاركة التفاصيل المتاحة','Share available details')]], reply: c('سأراجع اختيارات المنتج المسجلة وأشاركك المتاح منها.','I’ll check the product options listed and share what is available.'), next: c('تابع اختيار العميل وسجّل الطلب عند تأكيده','Follow the customer’s choice and record the order when confirmed') },
  ]
  const s = items[tab]
  const steps = [
    [c('العميل يكتب','Customer writes'), <div className="scn-bubble"><small>{s.ch}</small>{tx(s.msg, locale)}</div>],
    [c('معلومات المنتج المتاحة','Available product details'), <dl>{s.f.map(([k, v]) => <div key={k.en}><dt>{tx(k, locale)}</dt><dd>{tx(v, locale)}</dd></div>)}</dl>],
    [c('مساعد العملاء يجيب عند تفعيله','Customer assistant answers when enabled'), <><div className="scn-bubble ai"><small>AI</small>{tx(s.reply, locale)}</div><div className="scn-actions"><button className={ok ? 'is-approved' : ''} onClick={() => setOk(true)}><Check size={14}/> {ok ? tx(c('تمت المراجعة','Reviewed'), locale) : tx(c('مراجعة المحادثة','Review conversation'), locale)}</button><button className="muted">{tx(c('تعديل','Edit'), locale)}</button></div></>],
    [c('الخطوة التالية','Next step'), <><p>{tx(s.next, locale)}</p><span className="tag teal">{ok ? tx(c('تمت المراجعة','Reviewed'), locale) : tx(c('إجابة تلقائية · متابعة عند الحاجة','Automatic answer · follow-up when needed'), locale)}</span></>],
  ]
  return <section className="section section-scenario"><div className="container">
    <SectionIntro kicker={tx(c('رسالة من العميل','A customer message'), locale)} title={tx(c('من سؤال العميل إلى خطوة في دورة البيع.', 'From a customer question to the next step in a sale.'), locale)} body={tx(c('شاهد كيف يرتبط سؤال العميل بمعلومات المنتج والطلب، وكيف يكمل المسار إلى تسجيل البيع ومتابعة المخزون.', 'See how a customer question connects to product and order details, and how the journey continues through recording sales and tracking inventory.'), locale)}/>
    <div className="scn-tabs" role="tablist">{items.map((it, i) => <button key={it.ch} role="tab" aria-selected={i === tab} className={i === tab ? 'active' : ''} onClick={() => { setTab(i); setOk(false) }}>{tx(it.tab, locale)}</button>)}</div>
    <div className="scn-grid">{steps.map(([t, body], i) => <Reveal className="reveal-cell" key={i}><article className="scn-step"><span className="scn-num">0{i + 1}</span><h3>{tx(t, locale)}</h3>{body}</article></Reveal>)}</div>
    <div className="scn-note"><DemoBadge locale={locale}/></div></div></section>
}

function Faq({ locale }) {
  const qa = [
    [c('هل يجيب AI على أسئلة العملاء؟','Can AI answer customer questions?'), c('نعم. عند تفعيله، يجيب مساعد العملاء عن الأسئلة اعتمادًا على بيانات المتجر. ويستطيع الفريق متابعة المحادثة والتدخل عندما تحتاج الحالة إلى قرار.', 'Yes. When enabled, the customer assistant answers questions using your store data. Your team can follow the conversation and step in when a decision is needed.')],
    [c('ما القنوات التي يدعمها FIHRIST؟','Which channels does FIHRIST support?'), c('WhatsApp وMessenger وInstagram والبريد الإلكتروني وشات الموقع.', 'WhatsApp, Messenger, Instagram, email, and web chat.')],
    [c('هل يساعد في العثور على منتج؟','Can it help find a product?'), c('يساعد في فهم ما يبحث عنه العميل، والبحث في المنتجات المسجلة من وصفه أو الصورة التي يشاركها، ثم مراجعة السعر والتوفر والاختيارات المتاحة.', 'It helps understand what a customer needs, search listed products from a description or shared photo, and check available prices, stock, and options.')],
    [c('كيف يساعد AI التاجر؟','How does AI help merchants?'), c('يحلل مساعد المبيعات بيانات الطلبات والمبيعات والمخزون، ويقارن الأداء وحركة المنتجات والقنوات. تظل البيانات مصدر الأرقام، ولا يجزم المساعد بسبب لا تدعمه.', 'The sales-analysis assistant uses order, sales, and inventory data to compare performance, product movement, and channels. The data remains the source of the numbers; the assistant does not assert unsupported causes.')],
    [c('من أين أبدأ؟','Where do I start?'), c('ابدأ بالمحادثة والمنتج والطلب، ثم سجّل البيع وتابع ما بقي في المخزون. من هذه البيانات تظهر صورة أوضح للأداء والخطوة التالية.', 'Start with the conversation, product, and order, then record the sale and track what remains in stock. Those records provide a clearer view of performance and the next step.')],
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
