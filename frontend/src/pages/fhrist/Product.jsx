import React from 'react'
import { Layers3, MessageCircle, Database, Zap } from 'lucide-react'
import { c, tx, DetailHero, SectionIntro, FeatureGrid, Workflow } from '@/components/fihrist/Shared'

const pillars = [
  { icon: MessageCircle, title: c('محادثات ومساعدة للعملاء', 'Customer conversations and assistance'), body: c('اجمع WhatsApp وMessenger وInstagram والبريد وشات الموقع مع سجل العميل. عند تفعيل مساعد العملاء، يجيب تلقائيًا عن الأسئلة اعتمادًا على بيانات المتجر، ويستطيع الفريق متابعة المحادثة والتدخل عند الحاجة.', 'Bring WhatsApp, Messenger, Instagram, email, and web chat together with customer context. When enabled, the customer assistant answers questions automatically using store data, and your team can follow the conversation and step in when needed.'), href: '/conversations' },
  { icon: Database, title: c('المنتجات والطلبات والمخزون', 'Products, orders, and inventory'), body: c('اربط السعر والصورة والاختيارات بالطلب، وسجّل الكمية التي بيعت من كل اختيار لتعرف ما بقي. يعرّف رمز QR الصنف ويربطه بتسجيل البيع وحركة المخزون، مع صلاحيات للفريق.', 'Connect prices, images, and options to orders, and record what sold from each option to see what remains. QR codes identify each item and link it to its sales and inventory records, with team permissions.'), href: '/context' },
  { icon: Zap, title: c('متابعة وتحليل للمبيعات', 'Follow-up and sales analysis'), body: c('تغذي بيانات الطلبات والمبيعات والمخزون قراءة أداء المتجر. قارن الفترات وحركة المنتجات ونتائج القنوات، ونظّم المتابعة داخل FIHRIST، بينما يساعد مساعد تحليل المبيعات على شرح ما تدعمه البيانات.', 'Orders, sales, and inventory records inform the view of store performance. Compare periods, product movement, and channel results, organize follow-up within FIHRIST, and let the sales-analysis assistant explain what the data supports.'), href: '/automation' },
]

export default function Product({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المنصة', 'The platform')}
        title={c('نظام واحد يربط دورة البيع كاملة.', 'One system connects the full sales journey.')}
        body={c('من محادثة العميل والمنتج إلى الطلب والبيع والمخزون، ثم المتابعة وقراءة الأداء. تنتقل المعلومات بين الخطوات ليعمل فريقك على صورة واحدة.', 'From customer conversation and product to order, sale, and inventory, then follow-up and performance insights. Information carries across steps so your team can work from one connected view.')}
        icon={Layers3}
        variant="inbox"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('المنصة', 'The platform'), locale)}
            title={tx(c('كل ما يدعم البيع يعمل معًا.', 'Everything that supports a sale works together.'), locale)}
            body={tx(c('المحادثات ومعلومات المنتجات والطلبات والمبيعات والمخزون والمتابعة ورؤية المتجر ضمن دورة مترابطة.', 'Conversations, product details, orders, sales, inventory, follow-up, and store insight in one connected cycle.'), locale)}
          />
          <FeatureGrid items={pillars} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('كيف يعمل', 'How it works'), locale)}
            title={tx(c('من سؤال العميل إلى متابعة المتجر.', 'From a customer question to store follow-up.'), locale)}
            body={tx(c('ترتبط تفاصيل العميل والمنتج بالطلب والبيع والمخزون، ثم تساعد بيانات المتجر على قراءة النتائج وتنظيم المتابعة.', 'Customer and product details connect to orders, sales, and inventory; store data then helps review results and organize follow-up.'), locale)}
          />
          <Workflow locale={locale} />
          <div className="workflow-caption">
            <span className="caption-line"/>
            <span>{tx(c('عميل → محادثة → منتج → طلب → بيع → مخزون → متابعة ورؤية', 'Customer → conversation → product → order → sale → inventory → follow-up and insight'), locale)}</span>
            <span className="caption-line"/>
          </div>
        </div>
      </section>

    </>
  )
}
