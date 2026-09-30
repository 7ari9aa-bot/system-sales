import React from 'react'
import { FileText, UserPlus, KeyRound, Ban, Database, FileClock, XCircle, RotateCcw, Download } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints } from '@/components/fihrist/Shared'

const accountPoints = [
  { title: c('التسجيل', 'Registration'), body: c('حساب واحد لكل مستخدم، ببريد مهني صالح. لا حسابات مكررة.', 'One account per user, with a valid work email. No duplicate accounts.') },
  { title: c('الاستخدام المقبول', 'Acceptable use'), body: c('لا سبام، لا إساءة، لا أنشطة غير قانونية. الحسابات المخالفة تُعلَّق.', 'No spam, no abuse, no illegal activity. Violating accounts are suspended.') },
  { title: c('التجربة', 'Trials'), body: c('فترة تجريبية محدودة المدة والميزات. تنتهي تلقائيًا دون تجديد.', 'A time- and feature-limited trial. It ends automatically without renewal.') },
]

const ownershipPoints = [
  { title: c('ملكية البيانات', 'Data ownership'), body: c('كل بيانات عملائك ملكك بالكامل. نحن نخزّنها، لا نملكها.', 'All your customer data is entirely yours. We store it; we don\'t own it.') },
  { title: c('مخرجات AI', 'AI outputs'), body: c('الاقتراحات والتلخيصات ملكك بعد إنشائها. لا نعيد استخدامها.', 'Suggestions and summaries are yours after generation. We don\'t reuse them.') },
  { title: c('الترخيص', 'License'), body: c('نمنحك ترخيص استخدام المنصة مدة اشتراكك. لا نمنح ترخيصًا على بياناتك.', 'We grant you a license to use the platform during your subscription. We don\'t license your data.') },
]

const cancellationPoints = [
  { title: c('إلغاء في أي وقت', 'Cancel anytime'), body: c('لا عقود إلزامية. ألغِ من لوحة التحكم بنقرة واحدة.', 'No binding contracts. Cancel from the dashboard in one click.') },
  { title: c('حذف البيانات', 'Data deletion'), body: c('بعد الإلغاء، تُحذف بياناتك خلال 30 يومًا ما لم تطلب الإبقاء.', 'After cancellation, your data is deleted within 30 days unless you request retention.') },
  { title: c('الترحيل', 'Migration'), body: c('صدّر بياناتك قبل المغادرة بصيغة قابلة للنقل. لا احتجاز.', 'Export your data before leaving in a portable format. No lock-in.') },
]

export default function Terms({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الشروط', 'Terms')}
        title={c('شروط واضحة لبداية واضحة.', 'Clear terms for a clear start.')}
        body={c('نسخة توضيحية غير قانونية لاستخدامها في اختبار البنية فقط، وتحتاج مراجعة قانونية قبل النشر.', 'An illustrative, non-legal draft for structure testing only. It requires legal review before publication.')}
        icon={FileText}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الحساب', 'Account'), locale)}
            title={tx(c('من يفتح حسابًا ولماذا.', 'Who opens an account and why.'), locale)}
            body={tx(c('قواعد بسيطة وواضحة للتسجيل والاستخدام والتجربة.', 'Simple, clear rules for registration, usage, and trials.'), locale)}
          />
          <DetailPoints points={accountPoints} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الملكية', 'Ownership'), locale)}
            title={tx(c('بياناتك ملكك. مخرجات AI ملكك.', 'Your data is yours. AI outputs are yours.'), locale)}
            body={tx(c('لا غموض في الملكية. ما تضعه في المنصة يبقى لك.', 'No ambiguity in ownership. What you put in the platform stays yours.'), locale)}
          />
          <DetailPoints points={ownershipPoints} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الإلغاء', 'Cancellation'), locale)}
            title={tx(c('غادر متى شئت، ببياناتك معك.', 'Leave whenever you want, with your data.'), locale)}
            body={tx(c('لا عقود ملزمة، لا احتجاز بيانات، لا رسوم خفية.', 'No binding contracts, no data lock-in, no hidden fees.'), locale)}
          />
          <DetailPoints points={cancellationPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]