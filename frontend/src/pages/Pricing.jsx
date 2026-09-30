import React, { useRef, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check } from 'lucide-react';
import { useI18n, T } from '@/lib/marketing-i18n';

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

const PLANS = [
  {
    key: 'starter',
    priceMonthly: 19, priceYearly: 15,
    features: ['pricing.feat.inbox', 'pricing.feat.context', 'pricing.feat.assistant'],
    popular: false,
  },
  {
    key: 'growth',
    priceMonthly: 49, priceYearly: 39,
    features: ['pricing.feat.inbox', 'pricing.feat.context', 'pricing.feat.assistant', 'pricing.feat.automation', 'pricing.feat.api'],
    popular: true,
  },
  {
    key: 'scale',
    priceMonthly: 99, priceYearly: 79,
    features: ['pricing.feat.inbox', 'pricing.feat.context', 'pricing.feat.assistant', 'pricing.feat.automation', 'pricing.feat.sso', 'pricing.feat.api', 'pricing.feat.dedicated', 'pricing.feat.audit'],
    popular: false,
  },
];

export default function Pricing() {
  const { locale } = useI18n();
  const [yearly, setYearly] = useState(true);

  return (
    <>
      <section className="relative overflow-hidden grid-lines">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(59,130,246,0.10),transparent_70%)]" />
        <div className="relative max-w-[1240px] mx-auto px-6 pt-24 pb-16 text-center">
          <div className="eyebrow-accent mb-5 flex items-center justify-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
            <T k="pricing.eyebrow" />
          </div>
          <h1 className="font-display font-bold tracking-[-0.045em] leading-[1.08] text-[clamp(40px,6vw,72px)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
            <T k="pricing.title" />
          </h1>
          <p className="mt-6 max-w-[560px] mx-auto text-[17px] leading-[1.85] text-[var(--ink-2)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
            <T k="pricing.lede" />
          </p>

          {/* Billing toggle — fixed-width, position never moves */}
          <div className="mt-9 inline-flex items-center gap-1 p-1 rounded-md border-[0.5px] border-[var(--line)] bg-[var(--surface-2)]">
            <button
              onClick={() => setYearly(false)}
              className={`term px-4 h-9 rounded text-[12.5px] transition-colors ${!yearly ? 'bg-[var(--ink)] text-[var(--surface)]' : 'text-[var(--ink-3)]'}`}
            >
              <T k="pricing.monthly" />
            </button>
            <button
              onClick={() => setYearly(true)}
              className={`term px-4 h-9 rounded text-[12.5px] transition-colors flex items-center gap-2 ${yearly ? 'bg-[var(--ink)] text-[var(--surface)]' : 'text-[var(--ink-3)]'}`}
            >
              <T k="pricing.yearly" />
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent)]/15 text-[var(--accent)]"><T k="pricing.save" /></span>
            </button>
          </div>
        </div>
      </section>

      <section className="pb-28">
        <div className="max-w-[1240px] mx-auto px-6">
          <div className="grid md:grid-cols-3 gap-4">
            {PLANS.map((plan) => {
              const price = yearly ? plan.priceYearly : plan.priceMonthly;
              return (
                <Reveal key={plan.key}>
                  <article className={`surface-card p-8 h-full flex flex-col relative ${plan.popular ? 'border-[var(--accent)]' : ''}`}>
                    {plan.popular && (
                      <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 term text-[10px] px-3 py-1 rounded-full bg-[var(--accent)] text-white">
                        <T k="pricing.popular" />
                      </span>
                    )}
                    <h3 className="text-[20px] font-semibold text-[var(--ink)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
                      <T k={`pricing.${plan.key}`} />
                    </h3>
                    <p className="mt-2 text-[13px] text-[var(--ink-3)] leading-[1.7] min-h-[44px]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
                      <T k={`pricing.${plan.key}.d`} />
                    </p>
                    <div className="mt-6 flex items-baseline gap-1">
                      <span className="num text-[44px] text-[var(--ink)]">${price}</span>
                      <span className="text-[13px] text-[var(--ink-3)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="pricing.perMonth" /></span>
                    </div>
                    <Link to="/login" className={`mt-6 ${plan.popular ? 'btn-primary' : 'btn-secondary'}`}>
                      <T k="pricing.cta" /> <ArrowRight size={15} />
                    </Link>
                    <ul className="mt-7 space-y-3 pt-6 border-t-[0.5px] border-[var(--line)]">
                      {plan.features.map((f) => (
                        <li key={f} className="flex items-center gap-2.5 text-[13px] text-[var(--ink-2)]">
                          <Check size={14} className="text-[var(--accent)] flex-none" />
                          <span dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={f} /></span>
                        </li>
                      ))}
                    </ul>
                  </article>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>
    </>
  );
}