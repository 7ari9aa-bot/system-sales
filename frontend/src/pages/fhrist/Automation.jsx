import React from 'react'
import { Workflow as WorkflowIcon, Zap, Clock } from 'lucide-react'
import { c, DetailHero, SectionIntro, Workflow, FeatureGrid, DetailPoints } from '@/components/fihrist/Shared'

const ruleSteps = [
  c('متى تبدأ', 'When it starts'),
  c('الشرط', 'Condition'),
  c('ما الخطوة', 'What happens'),
  c('من يتابع', 'Who follows up'),
]
const ruleDescs = [
  c('عندما لا يرد العميل خلال مدة تحددها أو يتحقق شرط تختاره', 'When a customer does not reply within a time you set or a condition you define is met'),
  c('تحدد القاعدة متى تنطبق على العميل أو الطلب', 'The rule sets when it applies to a customer or order'),
  c('أنشئ تذكيرًا أو مهمة متابعة داخل FIHRIST', 'Create a reminder or follow-up task within FIHRIST'),
  c('حدد عضو الفريق الذي يتولى الخطوة التالية', 'Choose the teammate responsible for the next step'),
]

const templates = [
  { icon: Clock, title: c('متابعة عميل لم يرد', 'Follow up with a customer who has not replied'), body: c('إذا لم يرد العميل خلال المدة المحددة، أنشئ تذكيرًا للفريق بمتابعته.', 'If the customer does not reply within the set time, remind the team to follow up.') },
  { icon: Zap, title: c('مهمة عند تحقق شرط', 'A task when a condition is met'), body: c('عندما يتحقق شرط تحدده، أنشئ تذكيرًا للفريق بالخطوة التالية.', 'When a condition you define is met, remind the team of the next step.') },
  { icon: WorkflowIcon, title: c('تذكير للفريق', 'A team reminder'), body: c('وجّه مهمة متابعة إلى عضو الفريق المسؤول عن العميل.', 'Assign a follow-up task to the teammate responsible for the customer.') },
]

const controls = [
  { title: c('راجع القاعدة', 'Review the rule'), body: c('وضّح متى تبدأ القاعدة وما المهمة التي تنشئها ومن يتابعها.', 'Set when the rule starts, what task it creates, and who follows up.') },
  { title: c('أوقفها عند الحاجة', 'Pause it when needed'), body: c('تحكم في تشغيل قواعد المتابعة داخل FIHRIST.', 'Control follow-up rules within FIHRIST.') },
  { title: c('الفريق يتابع العمل', 'Your team follows the work'), body: c('تبقى متابعة العميل والطلب ضمن مسؤوليات فريق المتجر.', 'Customer and order follow-up stays with your store team.') },
]

export default function Automation({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('التذكيرات والمتابعة', 'Reminders and follow-up')}
        title={c('نظّم المتابعة داخل FIHRIST.', 'Organize follow-up within FIHRIST.')}
        body={c('أنشئ قواعد تذكّر الفريق بالمتابعة إذا لم يرد العميل خلال مدة تحددها أو عند تحقق شرط تختاره، وحدد من يتولى المهمة.', 'Set rules that remind the team to follow up if a customer does not reply within a time you choose or when a condition you define is met, and assign the task.')}
        icon={WorkflowIcon}
        variant="automation"
      />
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('طريقة العمل', 'How it works'), locale)}
            title={tx(c('حدد الحدث والشرط والخطوة والمسؤول.', 'Set the event, condition, next step, and owner.'), locale)}
            body={tx(c('توضح القاعدة متى تبدأ وما الذي يحدث بعدها ومن يتولى المتابعة.', 'A rule makes clear when it starts, what happens next, and who follows up.'), locale)}
          />
          <Workflow locale={locale} steps={ruleSteps} descs={ruleDescs} />
        </div>
      </section>
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('القوالب', 'Templates'), locale)}
            title={tx(c('ابدأ من أمثلة للمتابعة اليومية.', 'Start with everyday follow-up examples.'), locale)}
            body={tx(c('استخدمها كنقطة بداية، وحدد ما يناسب طريقة عمل متجرك.', 'Use them as a starting point and choose what fits your store\'s way of working.'), locale)}
          />
          <FeatureGrid items={templates} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('التحكم', 'Control'), locale)}
            title={tx(c('قواعد واضحة ومسؤولية للفريق.', 'Clear rules and team ownership.'), locale)}
            body={tx(c('تظل قواعد المتابعة مرتبطة بعمل الفريق ومسؤولياته.', 'Follow-up rules stay connected to your team and its responsibilities.'), locale)}
          />
          <DetailPoints points={controls} locale={locale} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
