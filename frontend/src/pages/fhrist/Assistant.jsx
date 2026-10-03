import React from 'react'
import { Bot, Sparkles, Target, MessageCircle } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, DetailPoints, Workflow } from '@/components/fihrist/Shared'

const doesFeatures = [
  { icon: Sparkles, title: c('يلخّص المحادثة', 'Summarizes the thread'), body: c('يختصر 20 رسالة في فقرة قابلة للقراءة قبل أن ترد.', 'Condenses 20 messages into a readable paragraph before you reply.') },
  { icon: Target, title: c('يستخرج النية', 'Extracts intent'), body: c('تحديد تلقائي: استفسار، طلب، شكوى — بدل القراءة اليدوية.', 'Automatic detection: question, order, complaint—instead of manual reading.') },
  { icon: MessageCircle, title: c('يصوغ الرد', 'Drafts the reply'), body: c('مسودة رد جاهزة للمراجعة والإرسال، بصياغة عربية واضحة.', 'A reply draft ready for review and sending, in clear Arabic.') },
]

const doesNotPoints = [
  { title: c('لا يرد وحده', 'No autonomous replies'), body: c('AI لا يرسل ردًا بدون موافقة بشرية. أبداً.', 'AI never sends a reply without human approval. Ever.') },
  { title: c('لا يتخذ قرارات', 'No autonomous decisions'), body: c('لا يصنف عميلًا أو يلغي طلبًا أو يغيّر حالة بشكل مستقل.', 'It doesn\'t classify, cancel, or change status on its own.') },
  { title: c('لا يبيع بياناتك', 'No data selling'), body: c('بياناتك تُستخدم لخدمتك فقط، لا للتدريب الخارجي.', 'Your data is used only to serve you, not for external training.') },
]

const approvalSteps = [
  c('AI يصوغ', 'AI drafts'),
  c('فريقك يراجع', 'Your team reviews'),
  c('اعتماد أو تعديل', 'Approve or edit'),
  c('سجل واضح', 'Clear audit trail'),
]

export default function Assistant({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('المساعد', 'Assistant')}
        title={c('AI يقترح، وفريقك يقرر.', 'AI suggests. Your team decides.')}
        body={c('تلخيص، استخراج، وصياغة للخطوة التالية — مع موافقة بشرية وسجل واضح لما حدث.', 'Summaries, extraction, and next-action drafts—with human approval and a clear audit trail.')}
        icon={Bot}
        variant="assistant"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('القدرات', 'Capabilities'), locale)}
            title={tx(c('ماذا يفعل AI.', 'What AI does.'), locale)}
            body={tx(c('ثلاث مهام: يلخّص، يفهم، ويصوغ — كلها تحت إشرافك.', 'Three tasks: summarize, understand, draft—all under your supervision.'), locale)}
          />
          <FeatureGrid items={doesFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الحدود', 'Limits'), locale)}
            title={tx(c('ماذا لا يفعل AI.', 'What AI does not do.'), locale)}
            body={tx(c('وضوح كامل في الحدود. لا مفاجآت، لا قرارات خفية.', 'Full clarity on limits. No surprises, no hidden decisions.'), locale)}
          />
          <DetailPoints points={doesNotPoints} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الاعتماد', 'Approval'), locale)}
            title={tx(c('مسار واضح: اقتراح ← مراجعة ← اعتماد.', 'A clear path: suggest → review → approve.'), locale)}
            body={tx(c('كل اقتراح يمر بمرحلة مراجعة بشرية قبل التنفيذ، مع سجل واضح لكل خطوة.', 'Every suggestion passes through human review before execution, with a clear log of each step.'), locale)}
          />
          <Workflow locale={locale} steps={approvalSteps} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]