import React from 'react'
import { Database, Clock, Eye, ShieldCheck, UserCog, FileClock, LockKeyhole } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid } from '@/components/fihrist/Shared'

const timelinePoints = [
  { title: c('الطلبات السابقة', 'Past orders'), body: c('ماذا طلب، متى، وبأي سعر — كل في مكان واحد.', 'What they ordered, when, and at what price—all in one place.') },
  { title: c('الملاحظات الداخلية', 'Internal notes'), body: c('ماذا قال فريقك عنه بعد آخر تفاعل، مرئي لمن يملك الصلاحية.', 'What your team said after the last interaction, visible to those with permission.') },
  { title: c('مصادر البيانات', 'Data sources'), body: c('من أين جاء كل سطر في السجل — محادثة، طلب، أو إدخال يدوي.', 'Where every line in the record came from—conversation, order, or manual entry.') },
]

const freshnessFeatures = [
  { icon: Eye, title: c('المصدر', 'Source'), body: c('كل معلومة موثقة بمصدرها الأصلي.', 'Every detail is tagged with its original source.') },
  { icon: Clock, title: c('الحداثة', 'Freshness'), body: c('وقت آخر تحديث ظاهر بجانب كل سطر في السجل.', 'Last-updated time visible next to every line in the record.') },
  { icon: FileClock, title: c('المراجعة', 'Audit trail'), body: c('من شاهد وعدّل كل تفصيل، ومتى.', 'Who viewed and edited every detail, and when.') },
]

const permissionPoints = [
  { title: c('صلاحيات حسب الدور', 'Role-based access'), body: c('لكل عضو فريق رؤية تتناسب مع مسؤولياته.', 'Each team member sees what fits their responsibilities.') },
  { title: c('سجل النشاط', 'Activity log'), body: c('كل قراءة وتعديل مسجل بوقته وصاحبه.', 'Every read and edit is logged with time and actor.') },
  { title: c('عزل البيانات', 'Data isolation'), body: c('بيانات كل عميل معزولة عن غيره.', 'Each customer\'s data is isolated from others.') },
]

export default function Context({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('السياق', 'Context')}
        title={c('اعرف من العميل، لا من آخر رسالة فقط.', 'Know the customer, not just the last message.')}
        body={c('اجمع سجل العميل والطلب والملاحظات في Timeline واحد قابل للمراجعة.', 'Bring customer history, requests, and notes into one reviewable timeline.')}
        icon={Database}
        variant="context"
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الخط الزمني', 'Timeline'), locale)}
            title={tx(c('كل ما يهم عن العميل في مكان واحد.', 'Everything that matters about a customer in one place.'), locale)}
            body={tx(c('لا تفتح ثلاثة تطبيقات لتعرف من ترد عليه. كل السياق أمامك قبل الرد.', 'Don\'t open three apps to know who you\'re replying to. All context is in front of you before you reply.'), locale)}
          />
          <DetailPoints points={timelinePoints} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الثقة في البيانات', 'Data trust'), locale)}
            title={tx(c('مصدر كل معلومة ووقت تحديثها.', 'The source and freshness of every detail.'), locale)}
            body={tx(c('لا توجد معلومة بلا مصدر. لا يوجد سجل بلا توقيت.', 'No information without a source. No record without a timestamp.'), locale)}
          />
          <FeatureGrid items={freshnessFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الصلاحيات', 'Permissions'), locale)}
            title={tx(c('من يرى ماذا.', 'Who sees what.'), locale)}
            body={tx(c('صلاحيات واضحة، سجل نشاط، وعزل بيانات — لكل عضو فريق.', 'Clear permissions, activity trail, and data isolation—for every team member.'), locale)}
          />
          <DetailPoints points={permissionPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]