import React from 'react'
import { ShieldCheck, UserCog, FileClock, Eye } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid } from '@/components/fihrist/Shared'

const lifecyclePoints = [
  { title: c('معلومات مترابطة', 'Connected information'), body: c('تساعد معلومات المحادثة والمنتج والطلب والبيع والمخزون فريقك على متابعة دورة البيع.', 'Conversation, product, order, sale, and inventory information help your team follow the sales journey.') },
  { title: c('صلاحيات الفريق', 'Team permissions'), body: c('تنظم الصلاحيات من يمكنه الوصول إلى معلومات العملاء والطلبات والعمل عليها.', 'Permissions organize who can access and work with customer and order information.') },
  { title: c('معلومات المتجر مصدر الأرقام', 'Store information supplies the numbers'), body: c('تعتمد الملخصات والمقارنات على بيانات المتجر المتاحة، ويساعد AI في شرح ما يظهر فيها.', 'Summaries and comparisons use available store data, and AI helps explain what it shows.') },
]

const permissionsFeatures = [
  { icon: UserCog, title: c('أدوار الفريق', 'Team roles'), body: c('حدد من يعمل على المحادثات والطلبات ومعلومات المتجر بحسب مسؤولياته.', 'Set who works with conversations, orders, and store information according to their responsibilities.') },
  { icon: FileClock, title: c('مسؤول واضح', 'Clear ownership'), body: c('عيّن مسؤولًا لمتابعة المحادثة أو الخطوة التالية ضمن عمل الفريق.', 'Assign someone to follow a conversation or next step within your team.') },
  { icon: Eye, title: c('تدخل عند الحاجة', 'Step in when needed'), body: c('يستطيع الفريق مواصلة المحادثة ومراجعة ما يحتاج إلى قرار أو متابعة.', 'Your team can continue a conversation and review what needs a decision or follow-up.') },
]

const governancePoints = [
  { title: c('مساعد محادثات العملاء', 'Customer conversation assistant'), body: c('عند تفعيله، يجيب اعتمادًا على بيانات المتجر، ويستطيع الفريق متابعة المحادثة والتدخل عند الحاجة.', 'When enabled, it answers using store data; your team can follow the conversation and step in when needed.') },
  { title: c('مساعد تحليل المبيعات', 'Sales-analysis assistant'), body: c('يحلل بيانات المبيعات ويلخص حركة المنتجات ونتائج القنوات المتاحة للتاجر.', 'Analyzes sales data and summarizes product movement and channel results for the merchant.') },
  { title: c('دور الفريق واضح', 'A clear role for your team'), body: c('يتدخل الفريق عندما تحتاج المحادثة إلى متابعة أو يحتاج القرار إلى مراجعة.', 'Your team steps in when a conversation needs follow-up or a decision needs review.') },
]

export default function Security({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الأمان والتحكم', 'Security & control')}
        title={c('الثقة تبدأ من وضوح ما يحدث.', 'Trust starts with clarity about what happens.')}
        body={c('تعرف كيف ترتبط معلومات العميل والمنتج والطلب بعمل فريقك، وأين يساعد AI وأين يتدخل الفريق.', 'See how customer, product, and order information connects to your team\'s work, where AI helps, and when your team steps in.')}
        icon={ShieldCheck}
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('معلومات البيع', 'Sales information'), locale)}
            title={tx(c('من المحادثة إلى قراءة أداء المتجر.', 'From conversation to store insight.'), locale)}
            body={tx(c('تساعد المعلومات المترابطة فريقك على متابعة العميل والمنتج والطلب، ثم مراجعة ما حدث.', 'Connected information helps your team follow the customer, product, and order, then review what happened.'), locale)}
          />
          <DetailPoints points={lifecyclePoints} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الصلاحيات', 'Permissions'), locale)}
            title={tx(c('من يصل لماذا.', 'Who accesses what.'), locale)}
            body={tx(c('تساعد الصلاحيات وتعيين المسؤوليات الفريق على تنظيم الوصول ومتابعة العمل.', 'Permissions and clear ownership help your team organize access and follow the work.'), locale)}
          />
          <FeatureGrid items={permissionsFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('المساعدة الذكية', 'AI assistance'), locale)}
            title={tx(c('مساعدة للعميل ورؤية للتاجر.', 'Help for customers and insight for merchants.'), locale)}
            body={tx(c('يساعد AI في أسئلة المنتجات وقراءة بيانات المتجر، بينما يظل للفريق دور في المتابعة والقرارات التي تحتاج إلى مراجعة.', 'AI helps with product questions and store data, while your team stays involved in follow-up and decisions that need review.'), locale)}
          />
          <DetailPoints points={governancePoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
