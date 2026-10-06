import React from 'react'
import { Bot, Sparkles, Target, MessageCircle } from 'lucide-react'
import { c, DetailHero, SectionIntro, FeatureGrid, DetailPoints, Workflow } from '@/components/fihrist/Shared'

const doesFeatures = [
  { icon: Sparkles, title: c('يفهم طلب العميل', 'Understands the customer\'s request'), body: c('يساعد في فهم ما يبحث عنه العميل، بما في ذلك وصف المنتج أو الصورة التي يشاركها.', 'Helps understand what a customer is looking for, including a product description or an image they share.') },
  { icon: Target, title: c('يبحث في معلومات المنتج', 'Checks product information'), body: c('يراجع السعر والتوفر والألوان والمقاسات والصور المسجلة في المتجر.', 'Checks the price, availability, colors, sizes, and images listed in your store.') },
  { icon: MessageCircle, title: c('إجابات تلقائية، وفريقك حاضر عند الحاجة.', 'Automatic answers, with your team involved when needed.'), body: c('يستطيع مشاركة صور المنتج المتاحة عندما يطلبها العميل، ويستطيع الفريق متابعة المحادثة والتدخل عندما تحتاج إلى قرار أو مساعدة شخصية.', 'It can share available product images when the customer asks. Your team can follow the conversation and step in when it needs a decision or personal help.') },
]

const doesNotPoints = [
  { title: c('مساعد محادثات العملاء', 'Customer conversation assistant'), body: c('عند تفعيله، يجيب عن أسئلة العملاء اعتمادًا على بيانات المتجر. ويستطيع الفريق متابعة المحادثة والتدخل إذا احتاجت الحالة إلى قرار.', 'When enabled, it answers customer questions using store data. Your team can follow the conversation and step in if a case needs a decision.') },
  { title: c('مساعد تحليل المبيعات للتاجر', 'Merchant sales-analysis assistant'), body: c('قارن المبيعات والطلبات بين الفترات، وراجع متوسط قيمة الطلب ونتائج القنوات. يشرح المساعد ما تدعمه البيانات، ويوضح عندما لا تكفي لتحديد السبب.', 'Compare sales and orders across periods, and review average order value and channel results. The assistant explains what the data supports and says when there is not enough evidence to establish a cause.') },
  { title: c('المعلومة والتفسير', 'Facts and interpretation'), body: c('بيانات المتجر هي مصدر الأرقام، ويساعد AI في شرحها. لا يثبت وحده سببًا أو يضمن نتيجة أو توقعًا.', 'Store data supplies the numbers and AI helps explain them. It does not establish causes or guarantee outcomes or predictions.') },
]

const customerSteps = [
  c('العميل يسأل', 'Customer asks'),
  c('المساعد يراجع بيانات المتجر', 'Assistant checks store data'),
  c('إجابة مباشرة عند التفعيل', 'Automatic answer when enabled'),
  c('الفريق يتابع أو يتدخل عند الحاجة', 'Your team follows up or steps in when needed'),
]

const customerDescs = [
  c('عن منتج أو تفاصيل متاحة في المتجر', 'About a product or details listed in your store'),
  c('ليجيب استنادًا إلى المعلومات المسجلة', 'So it can answer using the information listed'),
  c('يرد مساعد العملاء مباشرةً على سؤال العميل', 'The customer assistant answers the customer right away'),
  c('عندما تحتاج الحالة إلى قرار أو تدخل بشري', 'When a case needs a decision or human attention'),
]

export default function Assistant({ locale }) {
  return (
    <>
      <DetailHero
        locale={locale}
        kicker={c('مساعدة بالذكاء الاصطناعي', 'AI assistance')}
        title={c('مساعدة في المحادثة، وفريقك حاضر عند الحاجة.', 'Help in the conversation, with your team there when needed.')}
        body={c('عند تفعيله، يجيب مساعد العملاء عن الأسئلة اعتمادًا على بيانات المتجر. ويستطيع الفريق متابعة المحادثة والتدخل عندما تحتاج الحالة إلى قرار. وفي مساحة منفصلة، يساعد مساعد التاجر على فهم بيانات المبيعات.', 'When enabled, the customer assistant answers questions using store data. Your team can follow the conversation and step in when a case needs a decision. In a separate view, the merchant assistant helps make sense of sales data.')}
        icon={Bot}
        variant="assistant"
      />
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('محادثات العملاء', 'Customer conversations'), locale)}
            title={tx(c('إجابات تلقائية عند تفعيل مساعد العملاء.', 'Automatic answers when the customer assistant is enabled.'), locale)}
            body={tx(c('يستخدم مساعد العملاء بيانات متجرك للإجابة عن الأسئلة. ويستطيع فريقك متابعة المحادثة والتدخل عندما تحتاج الحالة إلى قرار.', 'The customer assistant uses your store data to answer questions. Your team can follow the conversation and step in when a case needs a decision.'), locale)}
          />
          <FeatureGrid items={doesFeatures} locale={locale} />
        </div>
      </section>
      <section className="section">
        <div className="container">
          <SectionIntro
            kicker={tx(c('نوعان من المساعدة', 'Two kinds of assistance'), locale)}
            title={tx(c('مساعد العملاء ومساعد تحليل المبيعات.', 'A customer assistant and a sales-analysis assistant.'), locale)}
            body={tx(c('الأول يجيب تلقائيًا على أسئلة العملاء عند تفعيله اعتمادًا على بيانات المتجر. والثاني يحلل بيانات المبيعات ليساعد التاجر على فهمها.', 'The first answers customer questions automatically when enabled, using store data. The second analyzes sales data to help merchants understand it.'), locale)}
          />
          <DetailPoints points={doesNotPoints} locale={locale} />
        </div>
      </section>
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('دور الفريق', 'Your team\'s role'), locale)}
            title={tx(c('إجابة تلقائية عند التفعيل، مع تدخل الفريق عند الحاجة.', 'Automatic answers when enabled, with your team stepping in when needed.'), locale)}
            body={tx(c('يجيب مساعد العملاء اعتمادًا على بيانات المتجر. ويمكن للفريق متابعة المحادثة والتدخل في الحالات التي تحتاج إلى قرار أو متابعة شخص.', 'The customer assistant answers using store data. Your team can follow the conversation and step in when a case needs a decision or personal follow-up.'), locale)}
          />
          <Workflow locale={locale} steps={customerSteps} descs={customerDescs} />
        </div>
      </section>

    </>
  )
}

const tx = (copy, locale) => copy[locale]
