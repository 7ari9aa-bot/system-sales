import React from 'react'
import { Inbox, MessageCircle, Mail, Globe2, Camera, Phone } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, Workflow, DetailPoints } from '@/components/fihrist/Shared'

const channels = [
  { icon: Phone, title: c('WhatsApp', 'WhatsApp'), body: c('تابع محادثات العملاء مع معلوماتهم وطلباتهم ضمن نفس مسار البيع.', 'Keep customer conversations connected to their context and orders in the same sales journey.') },
  { icon: MessageCircle, title: c('Messenger', 'Messenger'), body: c('اجمع رسائل العملاء مع سجلهم والخطوة التالية لفريقك.', 'Bring customer messages together with their history and your team\'s next step.') },
  { icon: Camera, title: c('Instagram', 'Instagram'), body: c('تابع رسائل العملاء وأسئلتهم عن المنتجات ضمن سياق المتجر.', 'Keep customer messages and product questions connected to your store context.') },
  { icon: Mail, title: c('البريد الإلكتروني', 'Email'), body: c('اربط استفسارات البريد بسجل العميل ومعلومات المنتج والطلب.', 'Connect email inquiries with customer, product, and order information.') },
  { icon: Globe2, title: c('شات الموقع', 'Web chat'), body: c('اجعل أسئلة زوار المتجر جزءًا من المحادثات التي يتابعها فريقك.', 'Bring store visitor questions into the conversations your team follows.') },
]

const responsePoints = [
  { title: c('مسؤول واضح', 'A clear owner'), body: c('اعرف من يتابع المحادثة، ومرّرها لعضو الفريق المناسب عند الحاجة.', 'See who is following a conversation and pass it to the right teammate when needed.') },
  { title: c('متابعة في وقتها', 'Timely follow-up'), body: c('استخدم تذكيرًا أو قاعدة متابعة داخل FIHRIST حتى لا تتوقف الخطوة التالية.', 'Use a reminder or a follow-up rule within FIHRIST to keep the next step moving.') },
  { title: c('سياق مع المحادثة', 'Context stays with the conversation'), body: c('تصل للمسؤول معلومات العميل والمنتج والطلب ذات الصلة لمواصلة العمل.', 'The teammate receives relevant customer, product, and order context to continue the work.') },
]

export default function Conversations({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المحادثات', 'Conversations')}
        title={c('كل محادثة بداية لمسار بيع أوضح.', 'Every conversation starts a clearer sales journey.')}
        body={c('اجمع أسئلة العملاء من WhatsApp وMessenger وInstagram والبريد وشات الموقع، واربط المحادثة بسجل العميل والمنتجات والطلبات والخطوة التالية.', 'Bring customer questions from WhatsApp, Messenger, Instagram, email, and web chat together, and connect each conversation to customer, product, order, and next-step details.')}
        icon={Inbox}
        variant="inbox"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('القنوات', 'Channels'), locale)}
            title={tx(c('تابع محادثات متجرك في مسار واحد.', 'Follow store conversations in one place.'), locale)}
            body={tx(c('اجمع القنوات الخمس مع سجل العميل والمنتج والطلب، حتى ينتقل السياق مع المحادثة.', 'Bring the five supported channels together with customer, product, and order context, so it carries with the conversation.'), locale)}
          />
          <FeatureGrid items={channels} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('كيف تعمل', 'How it works'), locale)}
            title={tx(c('من سؤال العميل إلى خطوة تالية.', 'From a customer question to the next step.'), locale)}
            body={tx(c('اعرف ما الذي يسأل عنه العميل، واربطه بالمنتج والطلب، ثم حدد من يتابع وما الذي يحتاجه.', 'Understand what the customer is asking, connect it to the product and order, then clarify who follows up and what they need.'), locale)}
          />
          <Workflow locale={locale} steps={[c('استقبل السؤال', 'Receive the question'), c('افهم طلب المنتج', 'Understand the product request'), c('أظهر سياق العميل', 'Bring in customer context'), c('عيّن من يتابع', 'Choose who follows up'), c('اربطه بالطلب', 'Connect it to the order')]} descs={[c('من WhatsApp أو Messenger أو Instagram أو البريد أو شات الموقع', 'From WhatsApp, Messenger, Instagram, email, or web chat'), c('اللون أو المقاس والسعر والتوفر والصورة حسب بيانات المنتج', 'Color, size, price, availability, and image from product details'), c('الطلبات والمحادثات ذات الصلة', 'Relevant orders and conversations'), c('الفريق يتدخل عند الحاجة أو عند طلب مراجعة', 'The team steps in when needed or when review is required'), c('تتحرك تفاصيل المحادثة مع مسار البيع', 'Conversation details carry through the sales journey')]} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الخطوة التالية', 'Next step'), locale)}
            title={tx(c('مسؤول وسياق ومتابعة.', 'An owner, context, and follow-up.'), locale)}
            body={tx(c('ساعد الفريق على معرفة من يتابع المحادثة وما يرتبط بها من منتج وطلب، ثم نظّم المتابعة داخل FIHRIST.', 'Help the team see who owns a conversation and which product or order relates to it, then organize follow-up within FIHRIST.'), locale)}
          />
          <DetailPoints points={responsePoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
