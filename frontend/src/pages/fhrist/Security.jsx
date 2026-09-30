import React from 'react'
import { ShieldCheck, LockKeyhole, Clock, Trash2, UserCog, FileClock, Eye } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid, PrincipleCard } from '@/components/fihrist/Shared'

const lifecyclePoints = [
  { title: c('التشفير', 'Encryption'), body: c('بياناتك مشفرة أثناء النقل (TLS) والتخزين (AES-256).', 'Your data is encrypted in transit (TLS) and at rest (AES-256).') },
  { title: c('الاحتفاظ', 'Retention'), body: c('تحكم في مدة بقاء كل نوع بيانات — محادثات، طلبات، سجلات.', 'Control how long each data type stays—conversations, orders, logs.') },
  { title: c('الحذف', 'Deletion'), body: c('احذف بيانات عميل بالكامل عند الطلب، مع سجل الحذف.', 'Delete a customer\'s data entirely on request, with a deletion log.') },
]

const permissionsFeatures = [
  { icon: UserCog, title: c('أدوار', 'Roles'), body: c('Admin وUser وصلاحيات مخصصة لكل فريق.', 'Admin, User, and custom permissions for each team.') },
  { icon: FileClock, title: c('سجل النشاط', 'Activity trail'), body: c('كل عملية مسجلة بقائلها ووقتها — قابل للتصدير.', 'Every operation is logged with actor and time—exportable.') },
  { icon: Eye, title: c('عزل البيانات', 'Data isolation'), body: c('كل عميل ومؤسسة في مساحة معزولة تمامًا.', 'Each customer and organization in a fully isolated space.') },
]

const governancePoints = [
  { title: c('مدخلات مفهومة', 'Understandable inputs'), body: c('تعرف بالضبط ما الذي يغذي كل اقتراح من AI.', 'You know exactly what feeds every AI suggestion.') },
  { title: c('مخرجات قابلة للمراجعة', 'Reviewable outputs'), body: c('كل اقتراح موثق بمصدره ووقته ومن راجعه.', 'Every suggestion is documented with source, time, and reviewer.') },
  { title: c('إشراف بشري', 'Human oversight'), body: c('لا قرار AI ينفذ بدون موافقة شخص — هذه قاعدة لا استثناء.', 'No AI decision executes without human approval—this is a rule without exception.') },
]

export default function Security({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الثقة والحوكمة', 'Trust & governance')}
        title={c('الثقة ليست Badge. إنها إجابة قابلة للمراجعة.', 'Trust is not a badge. It is an answer you can review.')}
        body={c('نعرض ما يحمي البيانات فعليًا، وما هو متاح في كل خطة وسوق، دون شهادات أو وعود غير موثقة.', 'We show what actually protects data and what is available by plan and market—without unsupported badges or promises.')}
        icon={ShieldCheck}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('دورة حياة البيانات', 'Data lifecycle'), locale)}
            title={tx(c('من الإدخال إلى الحذف.', 'From input to deletion.'), locale)}
            body={tx(c('ثلاث مراحل: تشفير، احتفاظ قابل للتحكم، وحذف نهائي عند الطلب.', 'Three stages: encryption, controllable retention, and permanent deletion on request.'), locale)}
          />
          <DetailPoints points={lifecyclePoints} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الصلاحيات', 'Permissions'), locale)}
            title={tx(c('من يصل لماذا.', 'Who accesses what.'), locale)}
            body={tx(c('أدوار واضحة، سجل نشاط كامل، وعزل بيانات صارم.', 'Clear roles, a full activity trail, and strict data isolation.'), locale)}
          />
          <FeatureGrid items={permissionsFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('حوكمة AI', 'AI governance'), locale)}
            title={tx(c('AI خاضع للمراجعة.', 'AI under review.'), locale)}
            body={tx(c('مدخلات واضحة، مخرجات موثقة، وإشراف بشري إلزامي.', 'Clear inputs, documented outputs, and mandatory human oversight.'), locale)}
          />
          <DetailPoints points={governancePoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]