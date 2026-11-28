import React, { useEffect } from 'react';
import { Globe2, ArrowRight, Check } from 'lucide-react';
import { MARKETS, LIVE_COUNTRIES, WAITLIST_COUNTRIES, DEFAULT_COUNTRY_SLUG, isCountryLive } from '@/lib/markets';
import { detectCountrySlug, rememberCountry } from '@/lib/country-detection';
import { useCountry } from '@/lib/CountryContext';
import { buildLocalizedRoute, resolveLocalizedPath } from '@/lib/public-seo-routes.mjs';

/**
 * Full page market and language selector shown at root `/`.
 */
export function MarketSelectorLanding() {
  const { locale, changeLocale } = useCountry();
  const isAr = locale === 'ar';

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center px-4 py-16 text-center">
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-muted/50 text-xs text-muted-foreground mb-6">
        <Globe2 size={14} className="text-primary" />
        <span>{isAr ? 'اختر دولتك ولغتك للبدء' : 'Select your country and language'}</span>
      </div>

      <h1 className="text-3xl md:text-5xl font-bold tracking-tight mb-4 text-foreground">
        {isAr ? 'منصة FIHRIST في الشرق الأوسط' : 'FIHRIST Platform in the Middle East'}
      </h1>
      <p className="max-w-xl text-muted-foreground text-sm md:text-base mb-12">
        {isAr
          ? 'نظام تشغيل المبيعات المتكامل للمتاجر. اختر دولتك للاطلاع على الميزات والأسعار المخصصة لسوقك.'
          : 'Sales operating system for stores. Choose your country to explore features and pricing tailored to your market.'}
      </p>

      {/* Language Toggle */}
      <div className="inline-flex p-1 rounded-lg border border-border bg-card mb-10">
        <button
          type="button"
          onClick={() => changeLocale('ar')}
          className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${
            isAr ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          العربية
        </button>
        <button
          type="button"
          onClick={() => changeLocale('en')}
          className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${
            !isAr ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          English
        </button>
      </div>

      {/* Countries Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl w-full">
        {/* Live Markets */}
        {LIVE_COUNTRIES.map((m) => (
          <a
            key={m.slug}
            href={buildLocalizedRoute(m.slug, locale, '/')}
            className="group flex flex-col p-6 rounded-2xl border border-border bg-card hover:border-primary/50 hover:shadow-lg transition-all text-start"
          >
            <div className="text-4xl mb-4">{m.flag}</div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-lg text-foreground group-hover:text-primary transition-colors">
                {isAr ? m.nameAr : m.nameEn}
              </h3>
              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 font-medium">
                {isAr ? 'متاح الآن' : 'Live'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">
              {isAr ? `العملة: ${m.nameAr} (${m.symbolAr})` : `Currency: ${m.currency} (${m.symbolEn})`}
            </p>
            <div className="mt-auto flex items-center gap-1.5 text-xs font-medium text-primary">
              <span>{isAr ? 'دخول السوق' : 'Enter market'}</span>
              <ArrowRight size={14} className={isAr ? 'rotate-180' : ''} />
            </div>
          </a>
        ))}

        {/* Waitlist Markets */}
        {WAITLIST_COUNTRIES.map((m) => (
          <a
            key={m.slug}
            href={buildLocalizedRoute(m.slug, locale, '/')}
            className="group flex flex-col p-6 rounded-2xl border border-dashed border-border bg-card/50 hover:border-amber-500/50 transition-all text-start"
          >
            <div className="text-4xl mb-4">{m.flag}</div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-lg text-foreground">
                {isAr ? m.nameAr : m.nameEn}
              </h3>
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-600 font-medium">
                {isAr ? 'قريباً' : 'Waitlist'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">
              {isAr ? `العملة: ${m.symbolAr} • الانضمام لقائمة الانتظار` : `Currency: ${m.currency} • Join waitlist`}
            </p>
            <div className="mt-auto flex items-center gap-1.5 text-xs font-medium text-muted-foreground group-hover:text-amber-600">
              <span>{isAr ? 'سجل اهتمامك' : 'Join waitlist'}</span>
              <ArrowRight size={14} className={isAr ? 'rotate-180' : ''} />
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

/**
 * Compact dropdown or modal button in the header nav.
 */
export function MarketHeaderSelector() {
  const { country, market, locale, changeCountry, changeLocale } = useCountry();
  const [open, setOpen] = React.useState(false);
  const isAr = locale === 'ar';

  return (
    <div className="relative inline-block text-start">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-border/80 bg-background/80 hover:bg-muted text-xs font-medium transition-colors"
        aria-label="Select Country and Language"
      >
        <span className="text-base">{market.flag}</span>
        <span className="hidden sm:inline">{isAr ? market.nameAr : market.nameEn}</span>
        <span className="text-muted-foreground text-[11px] uppercase">({locale})</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute end-0 mt-2 w-64 rounded-xl border border-border bg-card shadow-xl p-3 z-50 animate-in fade-in zoom-in-95">
            <div className="text-[11px] font-semibold text-muted-foreground px-2 py-1 mb-1">
              {isAr ? 'الدول المتاحة' : 'Available Markets'}
            </div>
            <div className="space-y-1">
              {Object.values(MARKETS).map((m) => (
                <button
                  key={m.slug}
                  type="button"
                  onClick={() => {
                    changeCountry(m.slug);
                    setOpen(false);
                  }}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs transition-colors ${
                    m.slug === country ? 'bg-primary/10 text-primary font-semibold' : 'hover:bg-muted text-foreground'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base">{m.flag}</span>
                    <span>{isAr ? m.nameAr : m.nameEn}</span>
                  </div>
                  {m.slug === country && <Check size={14} />}
                  {m.launchStatus === 'waitlist' && m.slug !== country && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {isAr ? 'قريباً' : 'Soon'}
                    </span>
                  )}
                </button>
              ))}
            </div>

            <div className="border-t border-border mt-2 pt-2">
              <div className="text-[11px] font-semibold text-muted-foreground px-2 py-1 mb-1">
                {isAr ? 'اللغة' : 'Language'}
              </div>
              <div className="grid grid-cols-2 gap-1 px-1">
                <button
                  type="button"
                  onClick={() => {
                    changeLocale('ar');
                    setOpen(false);
                  }}
                  className={`py-1 text-xs rounded text-center transition-colors ${
                    isAr ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'
                  }`}
                >
                  العربية
                </button>
                <button
                  type="button"
                  onClick={() => {
                    changeLocale('en');
                    setOpen(false);
                  }}
                  className={`py-1 text-xs rounded text-center transition-colors ${
                    !isAr ? 'bg-primary text-primary-foreground' : 'hover:bg-muted text-muted-foreground'
                  }`}
                >
                  English
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}


/**
 * Root `/` — no country question, just the right market.
 *
 * The old landing asked every visitor to choose a country before they could see
 * anything. The country is a property of the request, so `/` now resolves it
 * from the edge (see country-detection) and replaces the URL with that market's
 * home. Egypt is the only live market today, so an unknown visitor lands there;
 * the header switcher still lets anyone choose by hand.
 */
export function RootRedirect() {
  const { locale } = useCountry();
  const activeLocale = locale || 'ar';

  // ``window.location.replace``, not the router: this component is also
  // rendered by the prerender step, which has no <Router> above it and threw
  // ``useNavigate() may be used only in the context of a <Router>`` — the
  // production build failed on exactly that. A market landing deserves a real
  // navigation anyway, and the effect never runs while prerendering.
  useEffect(() => {
    let alive = true;
    const go = (slug) => {
      if (!alive) return;
      rememberCountry(slug);
      window.location.replace(`/${slug}/${activeLocale}`);
    };
    detectCountrySlug()
      .then(go)
      .catch(() => go(DEFAULT_COUNTRY_SLUG));
    return () => {
      alive = false;
    };
  }, [activeLocale]);

  // A blank beat, never a picker: the redirect lands in a few hundred ms.
  // The heading is not decoration — the prerender step requires one <h1> on
  // every public page, and this page is still a real page for a crawler.
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl md:text-3xl font-bold text-foreground">
        {locale === 'en' ? 'Taking you to your market' : 'بنوديك على سوقك'}
      </h1>
      <p className="mt-3 text-sm text-muted-foreground" aria-busy="true">
        {locale === 'en'
          ? 'FIHRIST opens the pricing and features for the country you are in.'
          : 'FIHRIST يعرض الأسعار والميزات الخاصة بالبلد الذي أنت فيه.'}
      </p>
    </div>
  );
}


/**
 * Keeps a visitor on their own market's pages, whatever address they landed on.
 *
 * `/` already redirects by routing (307). This covers only the addresses that
 * name no market at all: it moves those to the detected one when that market is
 * LIVE. An address that names its country is left alone — /sa/en/pricing is
 * Saudi Arabia's page whatever geo says, and moving it to /eg/en/pricing showed
 * Egyptian prices under a Saudi address (e2e/seo-localized.spec.js asserts
 * this). It fires at most once per session so a wrong geo answer cannot start a
 * redirect loop.
 */
export function MarketAutoSwitch() {
  const { country, locale, basePath } = useCountry();

  useEffect(() => {
    let alive = true;
    let alreadySwitched = false;
    try {
      alreadySwitched = window.sessionStorage.getItem('fihrist:market-switched') === '1';
    } catch {
      alreadySwitched = false;
    }
    if (alreadySwitched) return undefined;

    detectCountrySlug()
      .then((slug) => {
        if (!alive || !slug || slug === country || !isCountryLive(slug)) return;
        // The address wins: a page that names its country is that country's page.
        if (resolveLocalizedPath(window.location.pathname).country) return;
        try {
          window.sessionStorage.setItem('fihrist:market-switched', '1');
        } catch {
          /* private mode: the path check still prevents a loop below */
        }
        if (window.location.pathname.startsWith(`/${slug}/`)) return;
        window.location.replace(`/${slug}/${locale}${basePath === '/' ? '' : basePath}`);
      })
      .catch(() => {});

    return () => {
      alive = false;
    };
  }, [country, locale, basePath]);

  return null;
}
