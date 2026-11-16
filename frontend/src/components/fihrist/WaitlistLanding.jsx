import React, { useState } from 'react';
import { CheckCircle2, Sparkles, Send } from 'lucide-react';
import { useCountry } from '@/lib/CountryContext';

export function WaitlistLanding() {
  const { market, locale } = useCountry();
  const isAr = locale === 'ar';
  const [submitted, setSubmitted] = useState(false);
  const [email, setEmail] = useState('');
  const [storeName, setStoreName] = useState('');
  const [phone, setPhone] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!email) return;
    // In local/preview, record the waitlist interest
    setSubmitted(true);
  };

  return (
    <div className="min-h-[70vh] flex flex-col items-center justify-center px-4 py-20 text-center">
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-xs text-amber-600 font-medium mb-6">
        <Sparkles size={14} />
        <span>
          {isAr
            ? `قريباً في ${market.nameAr} ${market.flag}`
            : `Coming Soon to ${market.nameEn} ${market.flag}`}
        </span>
      </div>

      <h1 className="text-3xl md:text-5xl font-bold tracking-tight mb-4 text-foreground">
        {isAr
          ? `نحن نجهّز FIHRIST لسوق ${market.nameAr}`
          : `We are preparing FIHRIST for ${market.nameEn}`}
      </h1>
      <p className="max-w-xl text-muted-foreground text-sm md:text-base mb-10">
        {isAr
          ? `نعمل حالياً على إتاحة بوابات الدفع والتكاملات المحلية المخصصة لـ ${market.nameAr}. سجّل اهتمامك لتكون أول من يحصل على وصول مبكر وعرض إطلاق خاص.`
          : `We are currently integrating local payment gateways and carriers for ${market.nameEn}. Join our waitlist to be first in line with an exclusive launch offer.`}
      </p>

      {submitted ? (
        <div className="max-w-md w-full p-8 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 text-center animate-in fade-in zoom-in-95">
          <CheckCircle2 size={40} className="text-emerald-500 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-foreground mb-1">
            {isAr ? 'تم تسجيلك بنجاح!' : 'You are on the waitlist!'}
          </h3>
          <p className="text-xs text-muted-foreground">
            {isAr
              ? `شكراً لاهتمامك. سنرسل لك إشعاراً ودعوة فور فتح التسجيل في ${market.nameAr}.`
              : `Thank you for your interest. We will notify you as soon as early access opens in ${market.nameEn}.`}
          </p>
        </div>
      ) : (
        <form
          onSubmit={handleSubmit}
          className="max-w-md w-full p-6 sm:p-8 rounded-2xl border border-border bg-card shadow-lg text-start"
        >
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                {isAr ? 'اسم المتجر أو العلامة التجارية' : 'Store or Brand Name'}
              </label>
              <input
                type="text"
                required
                value={storeName}
                onChange={(e) => setStoreName(e.target.value)}
                placeholder={isAr ? 'مثال: متجر الرياض' : 'e.g. Dubai Boutique'}
                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                {isAr ? 'البريد الإلكتروني' : 'Email Address'}
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@store.com"
                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                {isAr ? 'رقم الواتساب' : 'WhatsApp Number'}
              </label>
              <div className="flex gap-2">
                <span className="inline-flex items-center px-3 rounded-lg border border-border bg-muted text-xs text-muted-foreground font-mono">
                  {market.phoneCode}
                </span>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="50 123 4567"
                  className="flex-1 px-3 py-2 rounded-lg border border-border bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
            </div>

            <button
              type="submit"
              className="w-full py-2.5 px-4 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:opacity-90 transition-opacity flex items-center justify-center gap-2 mt-4"
            >
              <Send size={15} />
              <span>{isAr ? 'انضم لقائمة الانتظار' : 'Join Waitlist'}</span>
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
