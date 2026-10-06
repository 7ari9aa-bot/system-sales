import React from 'react'
import { Database, Clock, Eye, FileClock } from 'lucide-react'
import { c, DetailHero, SectionIntro, DetailPoints, FeatureGrid } from '@/components/fihrist/Shared'

const timelinePoints = [
  { title: c('العميل والمحادثة', 'Customer and conversation'), body: c('ابدأ بسجل العميل ومحادثته لتعرف ما الذي طلبه وما الذي يحتاجه.', 'Start with the customer and conversation details to understand what was requested and what is needed.') },
  { title: c('المنتج والطلب والبيع', 'Product, order, and sale'), body: c('اربط سؤال العميل بالمنتج واختياراته والطلب، ثم تابع ما تم بيعه وما بقي في المخزون.', 'Connect a customer question to the product, its options, and the order, then follow what sold and what remains in stock.') },
  { title: c('المخزون والخطوة التالية', 'Inventory and the next step'), body: c('سجّل ما تم بيعه وما بقي، واربطه بالطلب ليعرف الفريق ما الخطوة التالية.', 'Record what sold and what remains, linked to the order, so the team can see what comes next.') },
]

const freshnessFeatures = [
  { icon: Eye, title: c('مصدر المعلومة', 'Where information comes from'), body: c('اعرف إن كانت المعلومة مرتبطة بمحادثة أو منتج أو طلب في المتجر.', 'See whether information comes from a conversation, product, or store order.') },
  { icon: Clock, title: c('بيانات المنتج', 'Product details'), body: c('ارجع إلى السعر والتوفر واللون والمقاس والصور المسجلة للمنتج.', 'Refer to the product\'s listed price, availability, color, size, and images.') },
  { icon: FileClock, title: c('تاريخ العميل', 'Customer history'), body: c('اجمع التفاعلات والطلبات والملاحظات ذات الصلة قبل متابعة المحادثة.', 'Bring together relevant interactions, orders, and notes before continuing a conversation.') },
]

const permissionPoints = [
  { title: c('صلاحيات الفريق', 'Team permissions'), body: c('تنظم صلاحيات الوصول من يمكنه العمل على معلومات العملاء والطلبات.', 'Access permissions help determine who can work with customer and order information.') },
  { title: c('تسليم المسؤولية', 'Team handoff'), body: c('وجّه المحادثة للعضو المناسب ليكمل متابعة العميل والطلب.', 'Route the conversation to the right teammate to continue following the customer and order.') },
  { title: c('تدخل الفريق', 'Team involvement'), body: c('يبقى الفريق جزءًا من مسار البيع ويتدخل عندما يحتاج العميل أو القرار إلى متابعة شخص.', 'Your team remains part of the sales journey and steps in when a customer or decision needs a person.') },
]

export default function Context({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('السياق', 'Context')}
        title={c('السياق يربط العميل بمسار البيع كاملًا.', 'Context connects the customer to the full sales journey.')}
        body={c('من المحادثة إلى المنتج والطلب والبيع والمخزون، تنتقل التفاصيل ذات الصلة مع العميل ليتمكن الفريق من متابعة ما حدث والخطوة التالية.', 'Customer context carries from the conversation through the product, order, sale, and inventory, helping the team follow what happened and what comes next.')}
        icon={Database}
        variant="context"
      />
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('السياق في دورة البيع', 'Context across the sales journey'), locale)}
            title={tx(c('كل خطوة مرتبطة بما قبلها وما بعدها.', 'Every step stays connected to what came before and what comes next.'), locale)}
            body={tx(c('يرى الفريق محادثة العميل والمنتج والطلب والبيع والمخزون المرتبط بها في رحلة واحدة، مع اتصال كل تفصيل بالخطوة التالية.', 'The team can follow the related customer conversation, product, order, sale, and inventory in one journey, with each detail connected to the next.'), locale)}
          />
          <DetailPoints points={timelinePoints} locale={locale} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('تفاصيل ذات صلة', 'Relevant details'), locale)}
            title={tx(c('معلومات تساعدك على خدمة العميل.', 'Information that helps you serve the customer.'), locale)}
            body={tx(c('راجع بيانات المنتج والطلب وسجل التواصل المتاحة عند مواصلة المحادثة.', 'Refer to available product, order, and contact history as you continue the conversation.'), locale)}
          />
          <FeatureGrid items={freshnessFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('عمل الفريق', 'Team access'), locale)}
            title={tx(c('وصول يتناسب مع مسؤولية كل عضو.', 'Access suited to each teammate\'s role.'), locale)}
            body={tx(c('تساعد صلاحيات الفريق على تنظيم الوصول إلى معلومات العملاء والطلبات ومتابعة العمل.', 'Team permissions help organize access to customer and order information and follow-up work.'), locale)}
          />
          <DetailPoints points={permissionPoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
