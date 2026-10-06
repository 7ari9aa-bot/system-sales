import React from 'react'
import { CircleHelp, Phone, UserPlus, Clock } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'

const quickStarts = [
  { icon: Phone, title: c('ابدأ بمحادثات العملاء', 'Start with customer conversations'), body: c('تابع WhatsApp وMessenger وInstagram والبريد وشات الموقع ضمن مسار عمل متصل.', 'Follow WhatsApp, Messenger, Instagram, email, and web chat as part of a connected workflow.') },
  { icon: UserPlus, title: c('راجع سجل العميل', 'Review a customer record'), body: c('اربط المحادثات والملاحظات والمنتجات والطلبات ذات الصلة.', 'Connect relevant conversations, notes, products, and orders.') },
  { icon: Clock, title: c('نظّم الخطوة التالية', 'Organize the next step'), body: c('استخدم مهمة أو تذكيرًا لمتابعة العميل أو الطلب داخل FIHRIST.', 'Use a task or reminder to follow up on a customer or order within FIHRIST.') },
]

const troubleshootingPoints = [
  { title: c('محادثة لا تظهر', 'A conversation is missing'), body: c('راجع القناة التي وصل منها العميل وتأكد من إعداداتها داخل المتجر.', 'Check which channel the customer used and review its settings in your store.') },
  { title: c('لا تجد معلومات المنتج', 'Product information is missing'), body: c('راجع تفاصيل المنتج المسجلة، مثل السعر والاختيارات والتوفر والصور.', 'Review the product details listed, such as price, choices, availability, and images.') },
  { title: c('خطوة متابعة غير واضحة', 'The next step is unclear'), body: c('راجع سجل المحادثة والطلب، وحدد عضو الفريق الذي سيتابع.', 'Review the conversation and order, then choose the teammate who will follow up.') },
]

const escalationPoints = [
  { title: c('حدد الخطوة التي توقفت', 'Describe where you got stuck'), body: c('اذكر القناة أو المنتج أو الطلب والخطوة التي كنت تحاول إكمالها.', 'Include the channel, product, or order and the step you were trying to complete.') },
  { title: c('وضح ما الذي توقعته', 'Explain what you expected'), body: c('أضف وصفًا مختصرًا لما ظهر لك وما كنت تتوقع أن يحدث.', 'Briefly describe what you saw and what you expected to happen.') },
  { title: c('اطلب مساعدة مسؤول الفريق', 'Ask a team administrator'), body: c('إذا تعذر عليك الوصول إلى محادثة أو طلب، راجع صلاحيات فريقك.', 'If you cannot access a conversation or order, check your team permissions.') },
]

export default function Support({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الدعم', 'Support')}
        title={c('ابدأ من المهمة التي تريد إنجازها.', 'Start with the task you want to complete.')}
        body={c('إرشادات عملية لمتابعة المحادثات، ومراجعة سجل العميل، وربط المنتجات والطلبات بالخطوة التالية.', 'Practical guidance for following conversations, reviewing customer records, and connecting products and orders to the next step.')}
        icon={CircleHelp}
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('ابدأ من هنا', 'Start here'), locale)}
            title={tx(c('ثلاث بدايات لعمل يومي أوضح.', 'Three starting points for clearer daily work.'), locale)}
            body={tx(c('اختر ما يساعدك على مواصلة البيع وخدمة العميل.', 'Choose the guidance that helps you continue the sale and serve the customer.'), locale)}
          />
          <FeatureGrid items={quickStarts} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('حل المشكلات', 'Troubleshooting'), locale)}
            title={tx(c('المشكلات الشائعة وحلولها.', 'Common issues and their solutions.'), locale)}
            body={tx(c('قبل أن تسأل الدعم، جرب الحلول الثلاثة الأكثر شيوعًا.', 'Before asking support, try the three most common solutions.'), locale)}
          />
          <DetailPoints points={troubleshootingPoints} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('طلب المساعدة', 'Getting help'), locale)}
            title={tx(c('معلومات تساعد على فهم المشكلة.', 'Information that helps clarify an issue.'), locale)}
            body={tx(c('حدد القناة أو الطلب والخطوة التي توقفت عندها، وراجع صلاحيات الفريق عند الحاجة.', 'Name the channel or order and the step where you got stuck; check team permissions when needed.'), locale)}
          />
          <DetailPoints points={escalationPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
