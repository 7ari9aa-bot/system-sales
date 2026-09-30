import React from 'react'
import { Layers3, MessageCircle, Database, Zap } from 'lucide-react'
import { c, tx, DetailHero, SectionIntro, FeatureGrid, Workflow } from '@/components/fihrist/Shared'

const pillars = [
  { icon: MessageCircle, title: c('صندوق واحد', 'One inbox'), body: c('واتساب وماسنجر وإنستغرام في Inbox واحد. لكل محادثة مالك وموعد رد، فلا رسالة تنام بلا رد.', 'WhatsApp, Messenger, and Instagram in one inbox. Every thread has an owner and a response window—nothing sits unanswered.'), href: '/conversations' },
  { icon: Database, title: c('سياق كامل', 'Full context'), body: c('اعرف من العميل، وماذا طلب آخر مرة، وأين وصل طلبه — قبل أن ترد.', 'Know who the customer is, what they last asked, and where their order stands—before you reply.'), href: '/context' },
  { icon: Zap, title: c('متابعة لا تنسى', 'Follow-up that never forgets'), body: c('قواعد تذكّرك وتصعد لك قبل أن يبرد العميل. كل قاعدة مرئية وقابلة للإيقاف.', 'Rules that remind and escalate before a lead goes cold. Every rule is visible and can be paused.'), href: '/automation' },
]

export default function Product({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المنصة', 'The platform')}
        title={c('نظام تشغيل مبيعات، لا CRM آخر.', 'A sales operating system, not another CRM.')}
        body={c('يربط FIHRIST المحادثة بالعميل والطلب والخطوة التالية، ثم يترك لفريقك القرار الواضح.', 'FIHRIST connects the conversation to the customer, request, and next action—then keeps the decision clear for your team.')}
        icon={Layers3}
        variant="inbox"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('المنصة', 'The platform'), locale)}
            title={tx(c('ثلاث قدرات في مسار واحد.', 'Three capabilities in one path.'), locale)}
            body={tx(c('لا تجمع أدوات. اجمع قرارات.', 'Stop collecting tools. Start collecting decisions.'), locale)}
          />
          <FeatureGrid items={pillars} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('كيف يعمل', 'How it works'), locale)}
            title={tx(c('من رسالة عابرة إلى خطوة يملكها شخص.', 'From a passing message to an owned next action.'), locale)}
            body={tx(c('من أول سؤال إلى آخر متابعة، يحافظ FIHRIST على الخيط الذي يجعل المبيعات قابلة للفهم.', 'From the first question to the last follow-up, FIHRIST keeps the thread that makes sales understandable.'), locale)}
          />
          <Workflow locale={locale} />
          <div className="workflow-caption">
            <span className="caption-line"/>
            <span>{tx(c('محادثة → عميل → طلب → خطوة تالية', 'Conversation → customer → request → next action'), locale)}</span>
            <span className="caption-line"/>
          </div>
        </div>
      </section>

    </>
  )
}