import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles, Inbox, Users, Target, Workflow as WorkflowIcon, Database, Check, Search, SlidersHorizontal } from 'lucide-react';
import { useI18n, T } from '@/lib/marketing-i18n';
import LiveBackground from '@/components/LiveBackground';

function Reveal({ children, className = '' }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || el.getBoundingClientRect().top <= window.innerHeight) {
      el.classList.add('reveal-in');
      return;
    }
    el.classList.add('reveal-pre');
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) { el.classList.add('reveal-in'); obs.disconnect(); } }, { threshold: 0.12 });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return <div ref={ref} className={`reveal ${className}`}>{children}</div>;
}

function KineticHeadline() {
  const { t, locale } = useI18n();
  const words = [t('hero.kinetic.1'), t('hero.kinetic.2'), t('hero.kinetic.3')];
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setIndex((v) => (v + 1) % words.length), 2600);
    return () => window.clearInterval(timer);
  }, [words.length]);
  return (
    <h1 className="font-display font-bold tracking-[-0.045em] leading-[1.08] text-[clamp(40px,6vw,76px)] max-w-[820px]">
      <span dir={locale === 'ar' ? 'rtl' : 'ltr'} className="block">
        <T k="hero.title.1" />{' '}
        <span className="relative inline-flex h-[1.1em] overflow-hidden align-bottom min-w-[3ch]">
          {words.map((w, i) => (
            <span
              key={w}
              className={`absolute inset-0 text-[var(--accent)] transition-all duration-500 ${
                i === index ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
              }`}
            >
              {w}
            </span>
          ))}
        </span>
      </span>
      <T k="hero.title.2" as="span" className="block" />
    </h1>
  );
}

function Hero() {
  const { locale } = useI18n();
  return (
    <section className="relative overflow-hidden grid-lines">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(59,130,246,0.10),transparent_70%)]" />
      <div className="relative max-w-[1240px] mx-auto px-6 pt-24 pb-20">
        <div className="grid lg:grid-cols-[1.05fr_1fr] gap-16 items-center">
          <div className="lg:order-2">
            <div className="eyebrow-accent mb-5 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
              <T k="hero.eyebrow" />
            </div>
            <KineticHeadline />
            <p className="mt-7 max-w-[540px] text-[17px] leading-[1.85] text-[var(--ink-2)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
              <T k="hero.lede" />
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link to="/login" className="btn-primary">
                <T k="nav.start" />
                <ArrowRight size={15} />
              </Link>
              <Link to="/product" className="btn-secondary">
                <T k="cta.secondary" />
              </Link>
            </div>
            <div className="mt-6 flex items-center gap-2 text-[12px] text-[var(--ink-3)]">
              <Check size={13} className="text-[var(--accent)]" />
              <T k="hero.note" />
            </div>
          </div>

          <div className="lg:order-1"><ProductFrame variant="inbox" /></div>
        </div>
      </div>
    </section>
  );
}

function ProductFrame({ variant = 'inbox' }) {
  const { locale } = useI18n();
  const isAr = locale === 'ar';
  const [activeThread, setActiveThread] = useState(0);
  const [filter, setFilter] = useState('all');

  const threadData = isAr
    ? [
        ['عميل محتمل', 'هل العرض يشمل التوصيل؟', 'نية شراء عالية'],
        ['محادثة جديدة', 'أرسل تفاصيل الطلب', 'طلب جديد'],
        ['متابعة', 'متابعة بعد الاجتماع', 'متابعة'],
      ]
    : [
        ['Prospect', 'Does the quote include delivery?', 'High intent'],
        ['New thread', 'Sent order details', 'New request'],
        ['Follow-up', 'Post-meeting follow-up', 'Follow-up'],
      ];

  useEffect(() => {
    const timer = window.setInterval(() => setActiveThread((v) => (v + 1) % threadData.length), 4500);
    return () => window.clearInterval(timer);
  }, [threadData.length]);

  const visible = filter === 'all' ? threadData : filter === 'priority' ? threadData.slice(0, 2) : threadData.slice(1);
  const active = threadData[activeThread] || threadData[0];

  return (
    <div className="surface-card overflow-hidden" dir="ltr" aria-label={isAr ? 'لقطة تجريبية' : 'Illustrative interface'}>
      <div className="h-9 bg-[var(--surface-3)] flex items-center gap-3 px-3.5 border-b-[0.5px] border-[var(--line)]">
        <div className="flex gap-1.5">
          <i className="w-2.5 h-2.5 rounded-full bg-[#3B82F6]/60" />
          <i className="w-2.5 h-2.5 rounded-full bg-[var(--ink-3)]/40" />
          <i className="w-2.5 h-2.5 rounded-full bg-[var(--ink-3)]/40" />
        </div>
        <span className="term text-[10px] text-[var(--ink-3)] flex-1">app.fihrist.demo / inbox</span>
        <span className="flex items-center gap-1.5 text-[10px] text-[var(--ink-3)]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E]" /> Live
        </span>
      </div>
      <div className="flex min-h-[340px] bg-[var(--surface)]">
        <aside className="w-12 bg-[var(--surface-2)] border-r-[0.5px] border-[var(--line)] flex flex-col items-center gap-5 py-3.5">
          <div className="w-6 h-6 grid place-items-center bg-[var(--accent)] text-white term text-[11px] rounded">F</div>
          <Inbox size={16} className="text-[var(--ink-2)]" />
          <Users size={16} className="text-[var(--ink-3)]" />
          <Target size={16} className="text-[var(--ink-3)]" />
          <WorkflowIcon size={16} className="text-[var(--ink-3)]" />
        </aside>
        <div className="flex-1 p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <span className="eyebrow text-[9px]">INBOX / TODAY</span>
              <h3 className="mt-1.5 text-[16px] font-semibold text-[var(--ink)]" dir={isAr ? 'rtl' : 'ltr'}>
                {isAr ? 'المحادثات المهمة اليوم' : 'Priority conversations'}
              </h3>
            </div>
            <span className="w-7 h-7 rounded-full bg-[var(--accent)] text-white grid place-items-center text-[12px] font-bold">أ</span>
          </div>
          <div className="flex items-center gap-2.5 mb-3.5">
            <div className="flex-1 flex items-center gap-2 h-8 px-3 rounded border-[0.5px] border-[var(--line)] bg-[var(--surface-2)] text-[var(--ink-3)]">
              <Search size={12} />
              <span className="text-[11px]" dir={isAr ? 'rtl' : 'ltr'}>{isAr ? 'ابحث في المحادثات…' : 'Search conversations…'}</span>
            </div>
            <div className="flex gap-1">
              {[['all', isAr ? 'الكل' : 'All'], ['priority', isAr ? 'مهم' : 'Priority'], ['unread', isAr ? 'غير مقروء' : 'Unread']].map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => { setFilter(k); setActiveThread(0); }}
                  className={`text-[10px] px-2.5 h-8 rounded border-[0.5px] transition-colors ${
                    filter === k ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/5' : 'border-[var(--line)] text-[var(--ink-3)]'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button className="w-8 h-8 grid place-items-center border-[0.5px] border-[var(--line)] rounded text-[var(--ink-3)]">
              <SlidersHorizontal size={12} />
            </button>
          </div>
          <div className="grid grid-cols-[0.9fr_1.2fr] gap-3">
            <div className="surface-inset overflow-hidden">
              {visible.map(([name, preview, badge], vi) => {
                const i = filter === 'unread' ? vi + 1 : vi;
                return (
                  <button
                    key={name + i}
                    onClick={() => setActiveThread(i)}
                    className={`w-full flex items-center gap-2.5 p-2.5 border-b-[0.5px] border-[var(--line-soft)] text-left transition-colors ${
                      i === activeThread ? 'bg-[var(--accent)]/8' : ''
                    }`}
                  >
                    <span className={`w-6 h-6 rounded-full grid place-items-center text-[10px] font-bold flex-none ${
                      i === 1 ? 'bg-[var(--ink-3)]/20 text-[var(--ink-2)]' : 'bg-[var(--accent)]/15 text-[var(--accent)]'
                    }`}>
                      {name[0]}
                    </span>
                    <span className="min-w-0 flex-1">
                      <b className="block text-[10.5px] text-[var(--ink)] truncate" dir={isAr ? 'rtl' : 'ltr'}>{name}</b>
                      <small className="block text-[9px] text-[var(--ink-3)] truncate mt-0.5" dir={isAr ? 'rtl' : 'ltr'}>{preview}</small>
                    </span>
                    <em className="term text-[9px] text-[var(--ink-3)] not-italic">{i === activeThread ? (isAr ? 'الآن' : 'now') : `${i + 1}h`}</em>
                  </button>
                );
              })}
            </div>
            <div className="surface-inset p-4 flex flex-col gap-3 justify-end min-h-[210px]">
              <div className="bubble bg-[var(--surface-2)] rounded p-2.5 self-start max-w-[90%]" dir={isAr ? 'rtl' : 'ltr'}>
                <span className="text-[11px] text-[var(--ink)] block">{active[1]}</span>
                <small className="term text-[8px] text-[var(--ink-3)] block mt-1.5">10:42</small>
              </div>
              <div className="bubble rounded p-2.5 self-end max-w-[90%] bg-[var(--accent)]/12 text-[var(--accent)] flex gap-1.5 items-start" dir={isAr ? 'rtl' : 'ltr'}>
                <Sparkles size={12} className="mt-0.5 flex-none" />
                <span>
                  <span className="text-[11px] block">{isAr ? `استخرج: ${active[2]} + خطوة تالية` : `Extracted: ${active[2]} + next action`}</span>
                  <small className="term text-[8px] opacity-70 block mt-1.5">{isAr ? 'اقتراح AI' : 'AI suggestion'}</small>
                </span>
              </div>
              <div className="flex gap-1.5 flex-wrap">
                <span className="term text-[9px] px-2 py-1 rounded bg-[var(--accent)]/15 text-[var(--accent)]">{active[2]}</span>
                <span className="text-[9px] px-2 py-1 rounded bg-[var(--surface-2)] text-[var(--ink-2)]" dir={isAr ? 'rtl' : 'ltr'}>
                  {isAr ? 'التالي: أرسل العرض' : 'Next: send quote'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TrustStrip() {
  const { locale } = useI18n();
  return (
    <section className="border-y-[0.5px] border-[var(--line)] py-5">
      <div className="max-w-[1240px] mx-auto px-6 flex items-center gap-7 text-[12px] text-[var(--ink-3)]">
        <span dir={locale === 'ar' ? 'rtl' : 'ltr'} className="flex-1"><T k="trust.label" /></span>
        <div className="hidden md:flex gap-6 items-center term text-[12px] text-[var(--ink-2)]">
          <b>ALMADA</b><b>nūr</b><b>AFQ</b><b>رام</b><b>مدار</b>
        </div>
        <span className="eyebrow-accent flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
          <T k="trust.badge" />
        </span>
      </div>
    </section>
  );
}

function WorkflowSection() {
  const { locale } = useI18n();
  const steps = [
    ['workflow.s1', 'workflow.s1.d'],
    ['workflow.s2', 'workflow.s2.d'],
    ['workflow.s3', 'workflow.s3.d'],
    ['workflow.s4', 'workflow.s4.d'],
    ['workflow.s5', 'workflow.s5.d'],
  ];
  return (
    <section className="py-28">
      <div className="max-w-[1240px] mx-auto px-6">
        <Reveal className="max-w-[680px] mb-14">
          <div className="eyebrow-accent mb-3"><T k="workflow.eyebrow" /></div>
          <h2 className="font-display font-bold tracking-[-0.04em] text-[clamp(30px,4vw,48px)] leading-[1.15]"><T k="workflow.title" /></h2>
          <p className="mt-4 text-[16px] text-[var(--ink-2)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="workflow.lede" /></p>
        </Reveal>
        <Reveal>
          <div className="flex items-start justify-between gap-2">
            {steps.map(([titleKey, descKey], i) => (
              <div key={titleKey} className="relative flex flex-col items-center text-center" style={{ width: '19%' }}>
                <div className="relative w-full flex justify-center mb-4">
                  <span className="term text-[11px] text-[var(--accent)] z-10 bg-[var(--surface)] px-2">{String(i + 1).padStart(2, '0')}</span>
                  {i < steps.length - 1 && <span className="absolute top-1/2 left-1/2 w-full h-px bg-[var(--line)]" />}
                </div>
                <b className="text-[13.5px] text-[var(--ink)] mb-2" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={titleKey} /></b>
                <small className="text-[12px] text-[var(--ink-3)] leading-[1.7]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={descKey} /></small>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

const FEATURES = [
  { icon: Inbox, t: 'features.f1.t', d: 'features.f1.d' },
  { icon: Database, t: 'features.f2.t', d: 'features.f2.d' },
  { icon: Sparkles, t: 'features.f3.t', d: 'features.f3.d' },
  { icon: WorkflowIcon, t: 'features.f4.t', d: 'features.f4.d' },
];

function Features() {
  const { locale } = useI18n();
  return (
    <section className="py-28 border-t-[0.5px] border-[var(--line)]">
      <div className="max-w-[1240px] mx-auto px-6">
        <Reveal className="max-w-[680px] mb-14">
          <div className="eyebrow-accent mb-3"><T k="features.eyebrow" /></div>
          <h2 className="font-display font-bold tracking-[-0.04em] text-[clamp(30px,4vw,48px)] leading-[1.15]"><T k="features.title" /></h2>
          <p className="mt-4 text-[16px] text-[var(--ink-2)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="features.lede" /></p>
        </Reveal>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {FEATURES.map((f) => (
            <Reveal key={f.t}>
              <article className="surface-card p-7 h-full flex flex-col" style={{ minHeight: 270 }}>
                <div className="w-10 h-10 grid place-items-center rounded-md bg-[var(--accent)]/10 text-[var(--accent)] mb-6">
                  <f.icon size={18} />
                </div>
                <h3 className="text-[18px] font-semibold text-[var(--ink)] mb-2.5" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={f.t} /></h3>
                <p className="text-[13px] text-[var(--ink-3)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={f.d} /></p>
                <Link to="/product" className="mt-auto pt-6 flex items-center gap-2 text-[12px] font-semibold text-[var(--accent)]">
                  <T k="features.link" /> <ArrowRight size={13} />
                </Link>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Proof() {
  const { locale } = useI18n();
  const stats = [
    ['proof.stat1.v', 'proof.stat1'],
    ['proof.stat2.v', 'proof.stat2'],
    ['proof.stat3.v', 'proof.stat3'],
  ];
  return (
    <section className="py-28 border-t-[0.5px] border-[var(--line)]">
      <div className="max-w-[1240px] mx-auto px-6 grid lg:grid-cols-[0.8fr_1.2fr] gap-16 items-center">
        <Reveal>
          <div className="eyebrow-accent mb-3"><T k="proof.eyebrow" /></div>
          <h2 className="font-display font-bold tracking-[-0.04em] text-[clamp(30px,4vw,48px)] leading-[1.15]"><T k="proof.title" /></h2>
          <p className="mt-4 text-[15px] text-[var(--ink-2)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="proof.lede" /></p>
          <Link to="/contact-sales" className="btn-primary mt-8">
            <T k="proof.cta" /> <ArrowRight size={15} />
          </Link>
        </Reveal>
        <Reveal>
          <div className="grid grid-cols-3 gap-4">
            {stats.map(([v, label]) => (
              <div key={label} className="surface-card aspect-square flex flex-col items-center justify-center text-center p-5">
                <span className="num text-[clamp(28px,3.5vw,42px)] text-[var(--ink)]"><T k={v} /></span>
                <span className="mt-3 text-[12px] text-[var(--ink-3)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={label} /></span>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function CTA() {
  const { locale } = useI18n();
  return (
    <section className="py-28 border-t-[0.5px] border-[var(--line)]">
      <div className="max-w-[1240px] mx-auto px-6">
        <Reveal className="surface-card p-12 lg:p-16 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_60%_at_50%_50%,rgba(59,130,246,0.12),transparent_70%)]" />
          <div className="relative">
            <h2 className="font-display font-bold tracking-[-0.04em] text-[clamp(30px,4vw,48px)] leading-[1.15]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="cta.title" /></h2>
            <p className="mt-4 max-w-[520px] mx-auto text-[16px] text-[var(--ink-2)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="cta.lede" /></p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <Link to="/login" className="btn-primary"><T k="cta.primary" /> <ArrowRight size={15} /></Link>
              <Link to="/product" className="btn-secondary"><T k="cta.secondary" /></Link>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  const { locale } = useI18n();
  const cols = [
    { title: 'footer.product', links: [['nav.platform', '/product'], ['nav.conversations', '/conversations'], ['nav.assistant', '/assistant']] },
    { title: 'footer.company', links: [['footer.about', '/product'], ['footer.contact', '/contact-sales']] },
    { title: 'footer.legal', links: [['footer.privacy', '/security'], ['footer.terms', '/security'], ['footer.security', '/security']] },
  ];
  return (
    <footer className="border-t-[0.5px] border-[var(--line)] py-14">
      <div className="max-w-[1240px] mx-auto px-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-10">
          <div>
            <div className="flex items-center gap-2.5 mb-4">
              <img src="/fihrist-mark.svg" alt="" className="w-7 h-7" />
              <span className="term text-[15px] text-[var(--ink)]">FIHRIST</span>
            </div>
            <p className="text-[12px] text-[var(--ink-3)] leading-[1.7] max-w-[200px]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
              {locale === 'ar' ? 'نظام تشغيل مبيعات عربي-first.' : 'Arabic-first sales operating system.'}
            </p>
          </div>
          {cols.map((col) => (
            <div key={col.title}>
              <div className="eyebrow mb-4"><T k={col.title} /></div>
              <ul className="space-y-2.5">
                {col.links.map(([k, to]) => (
                  <li key={k}>
                    <Link to={to} className="text-[13px] text-[var(--ink-2)] hover:text-[var(--ink)] transition-colors">
                      <T k={k} />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between pt-6 border-t-[0.5px] border-[var(--line)] text-[12px] text-[var(--ink-3)]">
          <span className="term">© 2026 FIHRIST</span>
          <span dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="footer.rights" /></span>
        </div>
      </div>
    </footer>
  );
}

export default function Home() {
  return (
    <>
      <LiveBackground />
      <Hero />
      <TrustStrip />
      <WorkflowSection />
      <Features />
      <Proof />
      <CTA />
      <Footer />
    </>
  );
}