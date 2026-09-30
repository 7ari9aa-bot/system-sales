import React from 'react'
import { Workflow as WorkflowIcon, Zap, Clock, Pause, RotateCcw, FileClock } from 'lucide-react'
import { c, DetailHero, SectionIntro, Workflow, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'

const ruleSteps = [
  c('المحفّز', 'Trigger'),
  c('الشرط', 'Condition'),
  c('الإجراء', 'Action'),
  c('المالك', 'Owner'),
]
const ruleDescs = [
  c('متى تعمل القاعدة: رسالة جديدة، تجاوز موعد، تغيير حالة', 'When the rule fires: new message, overdue, status change'),
  c('منطق التحقق: هل ينطبق؟ نعم → تابع', 'Check logic: does it apply? Yes → continue'),
  c('ماذا يحدث: أنشئ مهمة، أرسل ردًا، صدّر للنظام', 'What happens: create task, send reply, export'),
  c('من المسؤول: شخص محدد أو فريق', 'Who owns it: a specific person or team'),
]

const templates = [
  { icon: Clock, title: c('متابعة عرض السعر', 'Quote follow-up'), body: c('لا رد خلال 24 ساعة ← أنشئ مهمة متابعة وذكّر المندوب.', 'No reply in 24h → create a follow-up task and remind the rep.') },
  { icon: Zap, title: c('ترحيب العميل الجديد', 'New customer welcome'), body: c('رسالة ترحيب + إنشاء سجل عميل تلقائيًا من أول محادثة.', 'Welcome message + auto-create customer record from first conversation.') },
  { icon: WorkflowIcon, title: c('تصعيد التأخير', 'Overdue escalation'), body: c('تجاوز موعد الرد ← تصعيد للمسؤول التالي مع السياق كاملًا.', 'Response window passed → escalate to next owner with full context.') },
]

const controls = [
  { title: c('إيقاف مؤقت', 'Pause'), body: c('أوقف أي قاعدة بدون حذفها. أعد تشغيلها متى شئت.', 'Pause any rule without deleting it. Resume whenever you want.') },
  { title: c('سجل التنفيذ', 'Execution log'), body: c('كل تنفيذ مسجل بوقته ونتيجته ومن فعله.', 'Every execution is logged with time, result, and actor.') },
  { title: c('تراجع', 'Rollback'), body: c('الإجراءات قابلة للتراجع حتى بعد التنفيذ.', 'Actions can be rolled back even after execution.') },
]

export default function Automation({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('الأتمتة', 'Automation')}
        title={c('أتمتة قابلة للفهم والضبط.', 'Automation you can understand and control.')}
        body={c('حوّل القواعد المتكررة إلى Trigger وشرط وإجراء ومالك، مع إيقاف وتصعيد عند الحاجة.', 'Turn repeatable rules into a trigger, condition, action, and owner—with stop and escalation controls.')}
        icon={WorkflowIcon}
        variant="automation"
      />
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('كيف تعمل القواعد', 'How rules work'), locale)}
            title={tx(c('أربع خطوات لكل قاعدة.', 'Four steps for every rule.'), locale)}
            body={tx(c('كل قاعدة مبنية من نفس البنية: متى؟ هل؟ ماذا؟ من؟', 'Every rule is built from the same structure: when? if? what? who?'), locale)}
          />
          <Workflow locale={locale} steps={ruleSteps} descs={ruleDescs} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('القوالب', 'Templates'), locale)}
            title={tx(c('قوالب جاهزة، لا صفحة فارغة.', 'Ready templates, not a blank page.'), locale)}
            body={tx(c('ابدأ من قاعدة مجربة، عدّلها، ثم أطلقها.', 'Start from a proven rule, tweak it, then launch.'), locale)}
          />
          <FeatureGrid items={templates} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('الضبط', 'Control'), locale)}
            title={tx(c('إيقاف، تصعيد، وتراجع.', 'Pause, escalate, and roll back.'), locale)}
            body={tx(c('أنت تتحكم في كل قاعدة في كل لحظة. لا أتمتة تعمل في الخفاء.', 'You control every rule at every moment. No automation runs in the dark.'), locale)}
          />
          <DetailPoints points={controls} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]