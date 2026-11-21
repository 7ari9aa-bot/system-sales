import React from 'react'
import { Trash2, ListChecks, Clock, ShieldCheck } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid } from '@/components/fihrist/Shared'

// Every statement here is a thing the backend does: the Meta callback only OPENS a deletion
// request (modules/privacy/meta_deletion.py), the merchant erases from the privacy screen, and a
// closed workspace is kept 30 days (OFFBOARDING_RETENTION_DAYS) before it is deleted.

const steps = [
  { icon: ListChecks, title: c('1. افتح إعدادات فيسبوك', '1. Open your Facebook settings'), body: c('من حسابك على فيسبوك: الإعدادات، ثم «التطبيقات والمواقع الإلكترونية» (Apps and Websites).', 'On Facebook: Settings, then "Apps and Websites".') },
  { icon: Trash2, title: c('2. أزل تطبيق Fihrist', '2. Remove the Fihrist app'), body: c('اختر Fihrist ثم «إزالة». عند الإزالة تُرسل ميتا إلينا طلب حذف موقَّعًا تلقائيًا.', 'Select Fihrist and choose "Remove". Meta then sends us a signed deletion request automatically.') },
  { icon: Clock, title: c('3. احتفظ برمز التأكيد', '3. Keep your confirmation code'), body: c('نعيد إلى ميتا رمز تأكيد ورابط حالة، ويمكنك متابعة طلبك منهما في أي وقت.', 'We return a confirmation code and a status link to Meta, and you can follow your request with them at any time.') },
]

const guarantees = [
  { title: c('ما الذي يُحذف', 'What is deleted'), body: c('الرسائل والتعليقات والبيانات المرتبطة بمعرّفك على فيسبوك داخل مساحة عمل التاجر التي ربطت صفحتها.', 'The messages, comments and data tied to your Facebook ID inside the merchant workspace that connected the Page.') },
  { title: c('من ينفّذ الحذف', 'Who carries it out'), body: c('طلب ميتا يفتح طلب حذف فقط. يراجعه التاجر مالك البيانات وينفّذه من شاشة الخصوصية، حتى لا يستطيع طلب مزوَّر محو بيانات عملاء.', 'Meta\'s request only opens a deletion request. The merchant who owns the data reviews and runs it from the privacy screen, so a forged request cannot erase customer data.') },
  { title: c('المدة', 'How long'), body: c('عند إغلاق مساحة عمل كاملة نحتفظ بها 30 يومًا للتصدير ثم تُحذف نهائيًا.', 'When a whole workspace is closed we keep it for 30 days for export, then delete it permanently.') },
]

export default function DataDeletion({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('حذف البيانات', 'Data deletion')}
        title={c('احذف بياناتك من Fihrist.', 'Delete your data from Fihrist.')}
        body={c('تعليمات حذف البيانات التي وصلت إلينا عبر فيسبوك أو إنستجرام.', 'How to delete the data that reached us through Facebook or Instagram.')}
        icon={ShieldCheck}
        legal
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={c('الخطوات', 'Steps')[locale]}
            title={c('ثلاث خطوات.', 'Three steps.')[locale]}
            body={c('الطريقة الأسرع هي إزالة التطبيق من حسابك.', 'The fastest way is to remove the app from your account.')[locale]}
          />
          <FeatureGrid items={steps} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={c('التفاصيل', 'Details')[locale]}
            title={c('ماذا يحدث بعدها؟', 'What happens next?')[locale]}
            body={c('بالتحديد ما يفعله النظام، دون وعود عامة.', 'Exactly what the system does, without vague promises.')[locale]}
          />
          <DetailPoints points={guarantees} locale={locale} />
        </div>
      </section>
    </>
  )
}
