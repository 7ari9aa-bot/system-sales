import React from 'react'
import { LockKeyhole, User, MessageCircle, BarChart3, Server, ShieldCheck, Download, Trash2 } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid } from '@/components/fihrist/Shared'

const dataPoints = [
  { title: c('بيانات الحساب', 'Account data'), body: c('الاسم، البريد المهني، الدور، الإعدادات.', 'Name, work email, role, settings.') },
  { title: c('بيانات المحادثات', 'Conversation data'), body: c('الرسائل، المرفقات، حالة التسليم، الطوابع الزمنية.', 'Messages, attachments, delivery status, timestamps.') },
  { title: c('بيانات الاستخدام', 'Usage data'), body: c('تسجيلات الدخول، العمليات المنفذة، مؤشرات الأداء.', 'Logins, operations performed, performance metrics.') },
]

const usageFeatures = [
  { icon: Server, title: c('لتقديم الخدمة', 'To provide the service'), body: c('تشغيل الصندوق والمتابعة والسياق وكل ما يراه فريقك.', 'Running the inbox, follow-up, context, and everything your team sees.') },
  { icon: BarChart3, title: c('للتحسين', 'To improve'), body: c('فهم ما يعمل وما لا يعمل في المنتج — من بيانات الاستخدام فقط.', 'Understanding what works and what doesn\'t—from usage data only.') },
  { icon: ShieldCheck, title: c('لا للبيع', 'Never for sale'), body: c('لا نبيع بياناتك لأي طرف خارجي. ليست جزءًا من نموذجنا.', 'We never sell your data to any third party. It\'s not part of our model.') },
]

const rightsPoints = [
  { title: c('الوصول', 'Access'), body: c('اطلب نسخة كاملة من بياناتك في أي وقت.', 'Request a full copy of your data at any time.') },
  { title: c('التصدير', 'Export'), body: c('صدّر بياناتك بصيغة قابلة للنقل (JSON / CSV).', 'Export your data in a portable format (JSON / CSV).') },
  { title: c('الحذف', 'Deletion'), body: c('احذف حسابك وكل بياناتك نهائيًا عند الطلب.', 'Delete your account and all your data permanently on request.') },
]

export default function Privacy({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الخصوصية', 'Privacy')}
        title={c('ما البيانات؟ لماذا؟ وكم تبقى؟', 'What data? Why? And for how long?')}
        body={c('صفحة توضيحية تشرح أنواع البيانات وأغراض استخدامها وحقوق أصحابها.', 'An illustrative page explaining data types, purposes, and user rights.')}
        icon={LockKeyhole}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('ما نجمعه', 'What we collect'), locale)}
            title={tx(c('ثلاثة أنواع من البيانات.', 'Three types of data.'), locale)}
            body={tx(c('شفافية كاملة: ما نجمعه، ولماذا، وكم يبقى.', 'Full transparency: what we collect, why, and how long it stays.'), locale)}
          />
          <DetailPoints points={dataPoints} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الاستخدام', 'How we use it'), locale)}
            title={tx(c('نستخدم بياناتك لخدمتك فقط.', 'We use your data only to serve you.'), locale)}
            body={tx(c('ثلاثة أغراض واضحة. لا غير.', 'Three clear purposes. Nothing else.'), locale)}
          />
          <FeatureGrid items={usageFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('حقوقك', 'Your rights'), locale)}
            title={tx(c('بياناتك تحت سيطرتك.', 'Your data, your control.'), locale)}
            body={tx(c('ثلاث حقوق أساسية: الوصول، التصدير، والحذف.', 'Three fundamental rights: access, export, and deletion.'), locale)}
          />
          <DetailPoints points={rightsPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]