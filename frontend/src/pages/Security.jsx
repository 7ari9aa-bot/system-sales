import React, { useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Lock, ShieldCheck, FileText, MapPin } from 'lucide-react';
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

const PILLARS = [
  { icon: Lock, t: 'security.s1.t', d: 'security.s1.d' },
  { icon: ShieldCheck, t: 'security.s2.t', d: 'security.s2.d' },
  { icon: FileText, t: 'security.s3.t', d: 'security.s3.d' },
  { icon: MapPin, t: 'security.s4.t', d: 'security.s4.d' },
];

export default function Security() {
  const { locale } = useI18n();
  return (
    <>
      <section className="relative overflow-hidden grid-lines">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(59,130,246,0.10),transparent_70%)]" />
        <div className="relative max-w-[1240px] mx-auto px-6 pt-24 pb-20">
          <Reveal className="max-w-[760px]">
            <div className="eyebrow-accent mb-5 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
              <T k="security.eyebrow" />
            </div>
            <h1 className="font-display font-bold tracking-[-0.045em] leading-[1.08] text-[clamp(40px,6vw,72px)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
              <T k="security.title" />
            </h1>
            <p className="mt-7 max-w-[580px] text-[17px] leading-[1.85] text-[var(--ink-2)]" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
              <T k="security.lede" />
            </p>
          </Reveal>
        </div>
      </section>

      <section className="py-24 border-t-[0.5px] border-[var(--line)]">
        <div className="max-w-[1240px] mx-auto px-6">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {PILLARS.map((p) => (
              <Reveal key={p.t}>
                <article className="surface-card p-7 h-full flex flex-col" style={{ minHeight: 280 }}>
                  <div className="w-10 h-10 grid place-items-center rounded-md bg-[var(--accent)]/10 text-[var(--accent)] mb-6">
                    <p.icon size={18} />
                  </div>
                  <h3 className="text-[18px] font-semibold text-[var(--ink)] mb-2.5" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={p.t} /></h3>
                  <p className="text-[13px] text-[var(--ink-3)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k={p.d} /></p>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="py-28 border-t-[0.5px] border-[var(--line)]">
        <div className="max-w-[1240px] mx-auto px-6">
          <Reveal className="surface-card p-12 lg:p-16 text-center relative overflow-hidden">
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_60%_at_50%_50%,rgba(59,130,246,0.12),transparent_70%)]" />
            <div className="relative">
              <h2 className="font-display font-bold tracking-[-0.04em] text-[clamp(30px,4vw,48px)] leading-[1.15]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="cta.title" /></h2>
              <p className="mt-4 max-w-[520px] mx-auto text-[16px] text-[var(--ink-2)] leading-[1.8]" dir={locale === 'ar' ? 'rtl' : 'ltr'}><T k="cta.lede" /></p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <Link to="/login" className="btn-primary"><T k="cta.primary" /> <ArrowRight size={15} /></Link>
                <Link to="/contact-sales" className="btn-secondary"><T k="proof.cta" /></Link>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}