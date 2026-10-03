import React from 'react'
import { CircleHelp, Phone, UserPlus, Clock } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'

const quickStarts = [
  { icon: Phone, title: c('اربط أول قناة', 'Connect your first channel'), body: c('واتساب أو ماسنجر في أقل من 5 دقائق، بلا إعداد تقني معقد.', 'WhatsApp or Messenger in under 5 minutes, with no complex technical setup.') },
  { icon: UserPlus, title: c('أنشئ أول عميل', 'Create your first customer'), body: c('من رسالة واردة إلى سجل عميل كامل بنقرة واحدة.', 'From an incoming message to a full customer record in one click.') },
  { icon: Clock, title: c('ابنِ أول متابعة', 'Build your first follow-up'), body: c('قالب متابعة جاهز للتخصيص والإطلاق في دقائق.', 'A follow-up template ready to customize and launch in minutes.') },
]

const troubleshootingPoints = [
  { title: c('رسالة لا تصل', 'Messages not arriving'), body: c('تحقق من حالة التكامل والاتصال في صفحة القنوات.', 'Check integration status and connection in the Channels page.') },
  { title: c('رد لا يُرسل', 'Reply not sending'), body: c('تأكد من الصلاحيات وأن المحادثة غير مُغلقة أو مُعينة لشخص آخر.', 'Verify permissions and that the thread isn\'t closed or assigned elsewhere.') },
  { title: c('بيانات ناقصة', 'Missing data'), body: c('راجع المصدر ووقت آخر تحديث في سجل العميل.', 'Check the source and last-updated time in the customer record.') },
]

const escalationPoints = [
  { title: c('تصعيد حسب الخطة', 'Escalation by plan'), body: c('Starter ← بريد، Growth ← شات مباشر، Enterprise ← مدير حساب مخصص.', 'Starter → email, Growth → live chat, Enterprise → dedicated account manager.') },
  { title: c('أوقات الاستجابة', 'Response times'), body: c('مرتبطة بخطتك والسوق. تظهر بوضوح في لوحة التحكم.', 'Tied to your plan and market. Shown clearly in the dashboard.') },
  { title: c('حالة النظام', 'System status'), body: c('تحقق من حالة الخدمة قبل التصعيد — قد يكون الخلل عامًا.', 'Check service status before escalating—it may be a known issue.') },
]

export default function Support({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الدعم', 'Support')}
        title={c('ابدأ من أول نتيجة، لا من آخر وثيقة.', 'Start with the first outcome, not the last document.')}
        body={c('بوابة دعم مرتبة حسب المهمة: ربط قناة، إنشاء عميل، أو بناء أول متابعة.', 'A support hub organized around tasks: connect a channel, create a customer, or build your first follow-up.')}
        icon={CircleHelp}
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('ابدأ من هنا', 'Start here'), locale)}
            title={tx(c('ثلاث مهام، ثلاث نتائج.', 'Three tasks, three results.'), locale)}
            body={tx(c('اختر المهمة التي تريد إنجازها الآن. كل واحدة تنتهي بنتيجة واضحة.', 'Pick the task you want to accomplish now. Each ends with a clear result.'), locale)}
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
            kicker={tx(c('التصعيد', 'Escalation'), locale)}
            title={tx(c('متى وكيف تصعّد.', 'When and how to escalate.'), locale)}
            body={tx(c('مسار تصعيد واضح حسب ختك وسوقك. لا ضياع في القنوات.', 'A clear escalation path based on your plan and market. No getting lost in channels.'), locale)}
          />
          <DetailPoints points={escalationPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]