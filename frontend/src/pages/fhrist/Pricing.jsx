import React, { useState, useEffect } from 'react';
import { Target, Check, ShieldCheck, CreditCard } from 'lucide-react';
import { c, tx, DetailHero, Button } from '@/components/fihrist/Shared';
import { useCountry } from '@/lib/CountryContext';
import { WaitlistLanding } from '@/components/fihrist/WaitlistLanding';
import { resolveFaq, resolveContent } from '@/content/resolver';

export default function Pricing({ locale: propLocale }) {
  const { country, market, locale: ctxLocale, isWaitlist, formatPrice } = useCountry();
  const locale = propLocale || ctxLocale || 'ar';
  const isAr = locale === 'ar';

  const [billing, setBilling] = useState('monthly');
  const [marketData, setMarketData] = useState(null);
  const [_loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function fetchMarket() {
      try {
        const res = await fetch(`/api/v1/public/markets/${country}`);
        if (res.ok) {
          const data = await res.json();
          if (active) setMarketData(data);
        }
      } catch {
        // Fallback gracefully on network / SSR
      } finally {
        if (active) setLoading(false);
      }
    }
    fetchMarket();
    return () => {
      active = false;
    };
  }, [country]);

  // If this country is waitlisted, render the early access waitlist landing page
  if (isWaitlist) {
    return <WaitlistLanding />;
  }

  // Ratio for offline currency fallback (e.g. 1500 EGP ~ 120 SAR)
  const priceRatio = market.currency === 'EGP' ? 1.0 : 0.08;

  // Default plans if API is loading or offline
  const plans = marketData?.plans || [
    {
      code: 'starter',
      name: 'Starter',
      prices: [{ interval: 'month', price: 0, currency: market.currency }],
      features: {
        ar: ['3 مستخدمين', 'واتساب وويب شات', 'مساعد ذكي واحد'],
        en: ['3 Team Members', 'WhatsApp & WebChat', '1 AI Agent'],
      },
    },
    {
      code: 'pro',
      name: 'Pro',
      prices: [
        {
          interval: 'month',
          price: Math.round(1500 * priceRatio),
          currency: market.currency,
        },
      ],
      features: {
        ar: ['15 مستخدم', 'جميع قنوات التواصل', '10 مساعدين ذكاء اصطناعي', 'تقارير مبيعات متقدمة'],
        en: ['15 Team Members', 'All Channels', '10 AI Agents', 'Advanced Analytics'],
      },
    },
    {
      code: 'business',
      name: 'Business',
      prices: [
        {
          interval: 'month',
          price: Math.round(3500 * priceRatio),
          currency: market.currency,
        },
      ],
      features: {
        ar: ['40 مستخدم', 'جميع القنوات وبوابات الدفع', '25 مساعد ذكي', 'دعم مخصص'],
        en: ['40 Team Members', 'All Channels & Gateways', '25 AI Agents', 'Dedicated Support'],
      },
    },
  ];

  const faqs = resolveFaq(country, locale);
  const legalNotice = resolveContent(country, locale, 'legal')?.consumerNotice;

  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c(`باقات وأسعار ${market.nameAr} ${market.flag}`, `${market.nameEn} Plans & Pricing ${market.flag}`)}
        title={c(`اختر الباقة المناسبة لمتجرك في ${market.nameAr}`, `Choose the right plan for your store in ${market.nameEn}`)}
        body={c(
          `تسعير مرن بعملة ${market.currency} (${market.symbolAr}) بدون رسوم خفية. ابدأ مجاناً وطوّر متجرك مع نمو مبيعاتك.`,
          `Transparent pricing in ${market.currency} with zero hidden fees. Start free and scale as your sales grow.`
        )}
        icon={Target}
      />

      <section className="section pricing-section">
        <div className="container">
          <div className="pricing-toolbar">
            <div>
              <span className="kicker">{tx(c('خيارات الخطط', 'Plan options'), locale)}</span>
              <strong>{tx(c(`التسعير في ${market.nameAr}`, `Pricing in ${market.nameEn}`), locale)}</strong>
            </div>
            <div className="billing-toggle" role="group" aria-label={tx(c('دورة الفوترة', 'Billing cycle'), locale)}>
              <button
                type="button"
                className={billing === 'monthly' ? 'active' : ''}
                onClick={() => setBilling('monthly')}
              >
                {tx(c('شهري', 'Monthly'), locale)}
              </button>
              <button
                type="button"
                className={billing === 'annual' ? 'active' : ''}
                onClick={() => setBilling('annual')}
              >
                {tx(c('سنوي (وفر 15%)', 'Annual (Save 15%)'), locale)}
              </button>
            </div>
          </div>

          {/* Tax Disclosure Banner: Only rendered if standard VAT applies */}
          {market.taxRegime === 'standard' && (
            <div className="pricing-note">
              <span className="demo-badge">
                <ShieldCheck size={13} /> {tx(c('الشفافية الضريبية', 'Tax Policy'), locale)}
              </span>
              <span>
                {tx(
                  c(
                    `الأسعار المعروضة غير شاملة ضريبة القيمة المضافة (${(market.taxRate * 100).toFixed(0)}%) وفقاً للوائح ${market.taxAuthorityAr}.`,
                    `Displayed prices exclude VAT (${(market.taxRate * 100).toFixed(0)}%) per ${market.taxAuthorityEn} regulations.`
                  ),
                  locale
                )}
              </span>
            </div>
          )}

          <div className="pricing-grid">
            {plans.map((plan, i) => {
              const matchedPrice = plan.prices?.find((p) => p.interval === billing) || plan.prices?.[0];
              const priceValue = matchedPrice?.price ?? 0;
              const isFree = priceValue === 0;

              return (
                <article className={`price-card ${i === 1 ? 'featured' : ''}`} key={plan.code || plan.name}>
                  <span className="plan-kicker">0{i + 1} / {tx(c('خطة', 'PLAN'), locale)}</span>
                  <h3>{plan.name}</h3>

                  <div className="price">
                    {isFree ? (
                      tx(c('مجاناً', 'Free'), locale)
                    ) : (
                      formatPrice(billing === 'annual' ? Math.round(priceValue * 10) : priceValue)
                    )}
                    <small>
                      {isFree
                        ? tx(c('بدون بطاقة بنكية', 'No credit card needed'), locale)
                        : billing === 'annual'
                        ? tx(c('تدفع سنوياً', 'billed annually'), locale)
                        : tx(c('شهرياً', 'per month'), locale)}
                    </small>
                  </div>

                  <p>
                    {isFree
                      ? tx(c('مثالية للمتاجر الناشئة والبدايات السريعة.', 'Ideal for new stores and quick starts.'), locale)
                      : i === 1
                      ? tx(c('للمتاجر المتنامية التي تحتاج ميزات متقدمة.', 'For growing stores needing advanced sales tools.'), locale)
                      : tx(c('للمتاجر الكبرى والعمليات متعددة الفرق.', 'For high-volume operations and multi-team stores.'), locale)}
                  </p>

                  <ul>
                    {Array.isArray(plan.features) ? (
                      plan.features.map((f, idx) => (
                        <li key={idx}>
                          <Check size={15} /> {typeof f === 'string' ? f : tx(f, locale)}
                        </li>
                      ))
                    ) : plan.features?.[locale] ? (
                      plan.features[locale].map((f, idx) => (
                        <li key={idx}>
                          <Check size={15} /> {f}
                        </li>
                      ))
                    ) : (
                      <li>
                        <Check size={15} /> {tx(c('ميزات كاملة', 'All core features'), locale)}
                      </li>
                    )}
                  </ul>

                  <Button
                    href={`/register?country=${country}&plan=${plan.code}`}
                    kind={i === 1 ? 'primary' : 'secondary'}
                  >
                    {isFree
                      ? tx(c('ابدأ مجاناً الآن', 'Start Free Now'), locale)
                      : tx(c('اختر هذه الباقة', 'Select Plan'), locale)}
                  </Button>
                </article>
              );
            })}
          </div>

          {/* Verified Payment Methods Available in this Market */}
          {marketData?.payment_methods?.length > 0 && (
            <div className="mt-16 p-6 rounded-2xl border border-border bg-card/60 text-center">
              <div className="inline-flex items-center gap-2 text-xs font-semibold text-muted-foreground mb-3">
                <CreditCard size={15} className="text-primary" />
                <span>{isAr ? `طرق الدفع المدعومة في ${market.nameAr}` : `Supported Payment Methods in ${market.nameEn}`}</span>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-3">
                {marketData.payment_methods.map((pm) => (
                  <span
                    key={pm.key}
                    className="inline-flex items-center px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-medium text-foreground shadow-sm"
                  >
                    {isAr ? pm.name_ar : pm.name_en}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Country-Aware FAQ Section */}
          {faqs.length > 0 && (
            <div className="mt-20">
              <div className="text-center mb-10">
                <h3 className="text-2xl font-bold text-foreground">
                  {isAr ? `الأسئلة الشائعة حول باقات ${market.nameAr}` : `Frequently Asked Questions in ${market.nameEn}`}
                </h3>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto">
                {faqs.map((faq) => (
                  <div key={faq.id} className="p-6 rounded-2xl border border-border bg-card/60">
                    <h4 className="font-semibold text-foreground mb-2">{faq.q}</h4>
                    <p className="text-sm text-muted-foreground leading-relaxed">{faq.a}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Statutory Legal & Consumer Notice for Market */}
          {legalNotice && (
            <div className="mt-12 text-center text-xs text-muted-foreground max-w-2xl mx-auto">
              <p>{legalNotice}</p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
