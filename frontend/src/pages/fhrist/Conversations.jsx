import React from 'react'
import { Inbox, MessageCircle, Mail, Globe2, Camera, Phone } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, Workflow, DetailPoints } from '@/components/fihrist/Shared'

const channels = [
  { icon: Phone, title: c('WhatsApp Business', 'WhatsApp Business'), body: c('أكثر قناة يستخدمها عملاؤك. تكامل مباشر، لا قوائم انتظار منفصلة.', 'Your customers\' most-used channel. Direct integration, no separate queues.') },
  { icon: MessageCircle, title: c('Messenger', 'Messenger'), body: c('رد على رسائل فيسبوك من نفس الصندوق، بسياق العميل الكامل.', 'Reply to Facebook messages from the same inbox, with full customer context.') },
  { icon: Camera, title: c('Instagram', 'Instagram'), body: c('تعليقات ورسائل مباشرة في مكان واحد، بلا تبديل تطبيق.', 'Comments and DMs in one place—no app switching.') },
  { icon: Mail, title: c('البريد الإلكتروني', 'Email'), body: c('حوّل البريد إلى محادثات منظمة، لا صندوق فوضوي.', 'Turn email into organized conversations, not a chaotic inbox.') },
  { icon: Globe2, title: c('شات الموقع', 'Web chat'), body: c('استقبل زوار موقعك كمحادثات، لا كإشعارات تضيع.', 'Receive site visitors as conversations, not lost notifications.') },
]

const responsePoints = [
  { title: c('موعد رد متوقع', 'Expected response time'), body: c('لكل محادثة SLA واضح منذ أول رسالة، مرئي لكل الفريق.', 'Every thread gets a clear SLA from the first message, visible to the whole team.') },
  { title: c('تصعيد تلقائي', 'Auto-escalation'), body: c('إذا تجاوز الموعد، ينتقل للمسؤول التالي تلقائيًا مع السياق كاملًا.', 'If the window passes, it escalates to the next owner automatically with full context.') },
  { title: c('تسليم بشري', 'Human handoff'), body: c('عند الحاجة، ينتقل السياق كاملًا لشخص آخر بلا فقدان معلومة.', 'When needed, full context transfers to another person with zero information loss.') },
]

export default function Conversations({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المحادثات', 'Conversations')}
        title={c('الرسالة ليست نهاية المسار. إنها بدايته.', 'A message is not the end of the path. It is the beginning.')}
        body={c('استقبل، صنّف، عيّن، وتابع من Inbox واحد — مع حفظ الطريق إلى العميل والطلب.', 'Receive, classify, assign, and follow up from one inbox—while keeping the path to the customer and request.')}
        icon={Inbox}
        variant="inbox"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('القنوات', 'Channels'), locale)}
            title={tx(c('قنواتك كلها في مكان واحد.', 'All your channels in one place.'), locale)}
            body={tx(c('خمس قنوات، صندوق واحد، سياق واحد. لا تبديل تطبيقات، لا نسخ ولصق.', 'Five channels, one inbox, one context. No app switching, no copy-paste.'), locale)}
          />
          <FeatureGrid items={channels} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('كيف تعمل', 'How it works'), locale)}
            title={tx(c('من رسالة إلى مالك.', 'From a message to an owner.'), locale)}
            body={tx(c('كل رسالة تدخل الصندوق تمر بخمس خطوات حتى تصل لصاحب وخطوة تالية.', 'Every message entering the inbox passes through five steps until it reaches an owner and a next action.'), locale)}
          />
          <Workflow locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الاستجابة', 'Response'), locale)}
            title={tx(c('نوافذ استجابة واضحة.', 'Clear response windows.'), locale)}
            body={tx(c('لكل محادثة موعد رد متوقع. إذا تأخر، يصعد النظام تلقائيًا.', 'Every conversation has an expected response window. If it slips, the system escalates automatically.'), locale)}
          />
          <DetailPoints points={responsePoints} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]