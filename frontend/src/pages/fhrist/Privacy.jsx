import React from 'react'
import { LockKeyhole, BarChart3, Server, ShieldCheck } from 'lucide-react'
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

const metaPoints = [
  { title: c('ما نقرؤه', 'What we read'), body: c('رسائل صفحتك وتعليقات منشوراتها وبيانات الملف العام للمرسل (الاسم ومعرّف التطبيق) بعد أن يربط التاجر صفحته بإذنه.', 'Your Page\'s messages, the comments on its posts and the sender\'s public profile data (name and app-scoped ID), after the merchant connects the Page with their consent.') },
  { title: c('ما نفعله به', 'What we do with it'), body: c('نعرضه لفريق التاجر في صندوق الوارد، ونتيح الرد والنشر والإعجاب من الصفحة نفسها. لا نبيعه ولا نستخدمه للإعلانات.', 'We show it to the merchant\'s team in the inbox and let them reply, post and like as the Page. We never sell it or use it for advertising.') },
  { title: c('الصلاحيات المطلوبة', 'Permissions we request'), body: c('pages_manage_metadata وpages_read_user_content وpages_manage_posts وpages_manage_engagement، وكلها على صفحة اختارها التاجر فقط.', 'pages_manage_metadata, pages_read_user_content, pages_manage_posts and pages_manage_engagement, all limited to a Page the merchant chose.') },
  { title: c('حذف بياناتك من فيسبوك', 'Deleting your Facebook data'), body: c('أزل التطبيق من إعدادات فيسبوك أو اتبع التعليمات في صفحة حذف البيانات.', 'Remove the app in your Facebook settings or follow the instructions on the data deletion page.'), href: '/data-deletion' },
]

export default function Privacy({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الخصوصية', 'Privacy')}
        title={c('ما البيانات؟ لماذا؟ وكم تبقى؟', 'What data? Why? And for how long?')}
        body={c('ما نجمعه من بيانات، ولماذا، وحقوقك، بما فيها البيانات التي تصلنا عبر فيسبوك وإنستجرام.', 'What data we collect, why, and your rights, including the data that reaches us through Facebook and Instagram.')}
        icon={LockKeyhole}
        legal
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
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('فيسبوك وإنستجرام', 'Facebook & Instagram'), locale)}
            title={tx(c('بيانات ميتا: ما نقرؤه ولماذا.', 'Meta data: what we read and why.'), locale)}
            body={tx(c('نصل إلى صفحتك فقط بعد موافقتك، وبأقل الصلاحيات اللازمة.', 'We reach your Page only after your consent, with the minimum permissions needed.'), locale)}
          />
          <DetailPoints points={metaPoints} locale={locale} />
          <p style={{ textAlign: 'center', marginTop: 24 }}><a href="/data-deletion">{tx(c('تعليمات حذف البيانات', 'Data deletion instructions'), locale)}</a></p>
        </div>
      </section>
    </>
  )
}

const tx = (copy, locale) => copy[locale]