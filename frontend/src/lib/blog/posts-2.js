// Blog articles, part 2. Same rules as posts-1.js and posts-2.js:
//   * Practical, step-by-step advice a store owner can use without FIHRIST.
//   * FIHRIST appears only in the final section, only with capabilities it really has.
//   * No invented statistics, studies, customers, prices or guarantees.
// Body blocks: { h: heading } | { p: paragraph } | { ul: [items] } | { ol: [items] }

const c = (ar, en) => ({ ar, en });

export const POSTS_2 = {
  'crm-vs-order-log-difference': {
    date: '2026-11-15',
    minutes: 8,
    title: c('الفرق بين CRM وسجل الطلبات للمتاجر | FIHRIST', 'CRM vs Order Log: The Difference for Stores | FIHRIST'),
    description: c(
      'ما الفرق بين نظام CRM وسجل الطلبات؟ متى يكفيك أحدهما، ومتى تحتاج الاثنين مرتبطين لتبيع أكثر لنفس العملاء.',
      'What is the difference between a CRM and an order log? When one is enough, and when you need both linked to sell more to the same customers.',
    ),
    h1: c('الفرق بين CRM وسجل الطلبات', 'The difference between a CRM and an order log'),
    lede: c(
      'كثيرون يظنون أنهما شيء واحد، لأن كلًّا منهما "يسجّل العملاء". الحقيقة أن كل واحد يجيب عن سؤال مختلف، والخلط بينهما ينتهي إما بأداة تُشترى ولا تُستخدم، أو بمتجر يكبر بلا ذاكرة. هذا الدليل يفرّق بينهما بمثال محسوب، ثم يعطيك قاعدة قرار.',
      'Many people assume they are the same thing, because both "record customers". In fact each answers a different question, and confusing them ends either in a tool that gets bought and never used, or in a store that grows without memory. This guide separates them with a worked example, then gives you a decision rule.',
    ),
    body: [
      { h: c('الفرق في سطر واحد', 'The difference in one line') },
      { p: c(
        'سجل الطلبات يسأل: ماذا بعنا؟ نظام CRM يسأل: من اشترى، وما الخطوة التالية معه؟ الأول يحفظ المعاملة، والثاني يحفظ العلاقة. متجر يعرف مبيعاته ولا يعرف عملاءه يبيع مرة واحدة لكل شخص ثم يبدأ من الصفر، ومتجر يعرف عملاءه ولا يعرف أرقامه لا يستطيع أن يحدد أي منتج يستحق إعادة الطلب.',
        'An order log asks: what did we sell? A CRM asks: who bought, and what is the next step with them? The first keeps the transaction, the second keeps the relationship. A store that knows its sales but not its customers sells once to each person and then starts from zero, and a store that knows its customers but not its numbers cannot tell which item deserves a reorder or which month deserves preparation.',
      ) },

      { h: c('ما هو سجل الطلبات، وما يجيده', 'What an order log is, and what it does well') },
      { p: c(
        'سجل الطلبات مجموعة صفوف، كل صف معاملة واحدة. أهم ما فيه أن الأعمدة ثابتة: تاريخ الطلب، اسم العميل، المنتج، الكمية، السعر، وحالة الطلب. ثبات الأعمدة هو ما يحوّل دفترًا مبعثرًا إلى سجل يمكن أن تُسأل أسئلته ويُجمع بأرقامه.',
        'An order log is a set of rows, each row one transaction. The most important thing about it is that the columns are fixed: order date, customer name, product, quantity, price, and order status. Fixed columns are what turn a scattered notebook into a record whose questions can be asked and whose numbers can be totalled.',
      ) },
      { ul: [
        c('معرفة ما يجب تجهيزه اليوم: كل صف حالته "مؤكد" ولم يُشحن بعد.', 'Knowing what must be prepared today: every row marked "confirmed" that has not shipped.'),
        c('معرفة ما سُلِّم وما لم يُسلَّم، فلا يبقى طلب معلّقًا بلا متابعة.', 'Knowing what was delivered and what was not, so no order sits pending without follow-up.'),
        c('جمع إجمالي الأسبوع أو الشهر بعملية جمع بسيطة على عمود السعر.', 'Totalling a week or a month with a simple sum on the price column.'),
        c('كشف الأصناف الأكثر طلبًا من تكرار اسم المنتج في الصفوف.', 'Spotting the most requested items from repeated product names in the rows.'),
        c('الرجوع إلى سعر متفق عليه عند أي خلاف مع عميل.', 'Going back to an agreed price when a customer disputes it.'),
      ] },
      { p: c(
        'مثال محسوب صغير: عندك هذا الأسبوع أربعة صفوف فقط. صفان حالتهما "مؤكد" ولم يُشحنا، وصف "شُحن"، وصف "سُلِّم". نظرة واحدة تخبرك أن عليك تجهيز طلبين اليوم. هذا كل ما يفعله السجل، وهو أمر لا يُستهان به، لأن كثيرًا من المتاجر الصغيرة تحمل طلباتها في رأسها ثم تنسى واحدًا.',
        'A small worked example: this week you have only four rows. Two are marked "confirmed" and not shipped, one is "shipped", and one is "delivered". One glance tells you that two orders need preparing today. That is all the log does, and it is not a small thing, because many small stores carry their orders in their head and then forget one.',
      ) },

      { h: c('أين يتوقف سجل الطلبات', 'Where an order log stops') },
      { p: c(
        'السجل يجيد الإجابة عن المعاملة، ويتوقف عند الشخص. لو سألت: "هذا العميل، هل اشترى من قبل؟ وماذا اشترى؟ وهل وعدته بشيء؟" يبدأ البحث اليدوي: فرز الصفوف بالاسم، ثم قراءة كل صف، ثم محاولة تذكّر المحادثة. وإن كان الاسم مكتوبًا بصيغتين مختلفتين، وهو ما يحدث دائمًا، فقد تجد صفين ولا تجد الثالث.',
        'The log answers well about the transaction and stops at the person. If you ask: "this customer, did they buy before? What did they buy? Did I promise them anything?" manual searching begins: sort rows by name, read each row, then try to recall the conversation. And if the name was written in two different ways, which always happens, you may find two rows and miss the third.',
      ) },
      { p: c(
        'المشكلة الثانية أن السجل بلا مستقبل. كل أعمدته تصف ما حدث. لا يوجد عمود يجيب: متى أكلّمه مرة أخرى؟ من المسؤول عنه؟ ماذا ينتظر؟ لذلك تعيش المتابعة في ذاكرة صاحب المتجر، وذاكرة صاحب المتجر هي أول ما يُرهَق عندما تكثر الرسائل.',
        'The second problem is that the log has no future. All its columns describe what happened. No column answers: when do I speak to them again? Who owns them? What are they waiting for? So follow-up lives in the owner memory, and the owner memory is the first thing to wear out when messages pile up.',
      ) },

      { h: c('ما هو نظام CRM، وما يجيده', 'What a CRM is, and what it does well') },
      { p: c(
        'نظام CRM (إدارة علاقات العملاء) سجل واحد لكل شخص، لا لكل معاملة. هذا الفرق الصغير يغيّر طريقة العمل. داخل صفحة العميل تجد بياناته ومحادثاته وطلباته وملاحظاتك عنه والخطوة التالية المتفق عليها. أي شيء حدث معه في أي وقت يقع في مكان واحد، لأنك تبحث عن الشخص أولًا ثم ترى تاريخه كاملًا.',
        'A CRM (customer relationship management) system is one record per person, not per transaction. That small difference changes how work happens. Inside a customer page you find their details, conversations, orders, your notes about them, and the agreed next step. Anything that ever happened with them sits in one place, because you look up the person first and then see the whole history.',
      ) },
      { ul: [
        c('إجابة سريعة عن "من هو هذا؟" قبل أن تكتب أول كلمة في الرد.', 'A quick answer to "who is this?" before you type the first word of a reply.'),
        c('معرفة من اشترى أكثر من مرة، ومن اشترى مرة ثم توقف، دون فرز يدوي.', 'Knowing who bought more than once, and who bought once and stopped, without manual sorting.'),
        c('موعد متابعة واضح لكل عميل، موجود في مكان يراه غيرك أيضًا.', 'A clear follow-up date for each customer, stored where someone else can see it too.'),
        c('مسؤول محدد لكل عميل، فلا يسأل اثنان العميل نفسه ولا يُنسى أحد.', 'One named owner per customer, so two people do not ask the customer the same thing and nobody is forgotten.'),
        c('تسليم عميل من موظف إلى آخر دون أن يبدأ الثاني من الصفر.', 'Handing a customer from one employee to another without the second starting from zero.'),
      ] },
      { p: c(
        'الـ CRM لا يلغي الطلبات، بل يعرضها في سياقها: الطلب يظل صفًّا، لكنه مربوط بشخص تعرف تاريخه. السؤال ليس أي الأداة أفضل في المطلق، بل هل الأرقام والأشخاص في المكان نفسه أم في مكانين لا يلتقيان.',
        'A CRM does not cancel orders, it shows them in context: the order is still a row, but linked to a person whose history you know. The question is not which tool is better in the abstract, but whether the numbers and the people sit in the same place or in two places that never meet.',
      ) },

      { h: c('الفرق الحقيقي: وحدة العمل والزمن', 'The real difference: unit of work and time') },
      { p: c(
        'إن أردت قاعدة واحدة تحفظها، فهي أن وحدة العمل مختلفة. في السجل الوحدة هي الطلب، وفي الـ CRM الوحدة هي العميل. من هذا الفرق تتبع كل الفروق الأخرى في الزمن والغرض وطريقة الاستخدام اليومي.',
        'If you want one rule to remember, it is that the unit of work differs. In a log the unit is the order, in a CRM the unit is the customer. Every other difference in time, purpose, and daily use follows from this one.',
      ) },
      { ul: [
        c('الوحدة: صف معاملة في السجل، وصفحة شخص في الـ CRM.', 'Unit: a transaction row in a log, a person page in a CRM.'),
        c('الزمن: الماضي والحاضر في السجل، والمستقبل (المتابعة) في الـ CRM.', 'Time: past and present in a log, the future (follow-up) in a CRM.'),
        c('السؤال: "كم بعنا؟" مقابل "ما الخطوة التالية مع هذا العميل؟"', 'Question: "how much did we sell?" versus "what is the next step with this customer?"'),
        c('الاستخدام اليومي: التجهيز والشحن في السجل، والرد والإقناع في الـ CRM.', 'Daily use: packing and shipping in the log, replying and convincing in the CRM.'),
        c('من يستخدمه: من يجهّز الطلبات في السجل، ومن يتحدث مع العملاء في الـ CRM.', 'Who uses it: whoever prepares orders in the log, whoever talks to customers in the CRM.'),
      ] },
      { p: c(
        'هذا لا يعني أن أحدهما أعلى مرتبة. متجر يبيع صنفًا واحدًا لمرة واحدة لكل عميل يحتاج سجلًا نظيفًا لا إدارة علاقات، ومتجر يعيش على العميل العائد يحتاج الاثنين مرتبطين لا منفصلين.',
        'This does not mean one ranks above the other. A store selling one item once to each customer needs a clean log rather than relationship management, and a store that lives on returning customers needs both, linked rather than separate.',
      ) },

      { h: c('مثال عملي على نفس البيانات', 'A worked example on the same data') },
      { p: c(
        'تخيّل متجر ملابس صغير. عميلة راسلتك قبل شهرين تسأل عن فستان بمقاس معين، وأخبرتها أن المقاس غير متوفر. ثم عادت بعد أسبوعين تسأل عن سعر قطعة أخرى، ولم تكمل. ثم اشترت قطعة صغيرة مرة واحدة. ثلاث تفاعلات وطلب واحد، هذا كل ما حدث.',
        'Imagine a small clothing store. A customer messaged two months ago asking about a dress in a specific size, and you told her that size was out of stock. Two weeks later she came back asking the price of another piece and did not complete. Then she bought one small item once. Three interactions and one order, that is all that happened.',
      ) },
      { p: c(
        'في سجل الطلبات ستجد صفًّا واحدًا فقط، لأن ما قبل الشراء لم يتحول إلى طلب. الرسالتان تعيشان في المحادثة، وقد تُدفن تحت عشرات الرسائل بعد أسبوع. النتيجة أنك ترى عميلة اشترت مرة، وهذا كل ما تعرفه عنها عند أول رسالة جديدة.',
        'In the order log you will find only one row, because nothing before the purchase became an order. The two messages live in the chat and may be buried under dozens of messages a week later. The result is that you see a customer who bought once, and that is all you know about her when a new message arrives.',
      ) },
      { p: c(
        'في الـ CRM ترى الصفحة نفسها: سألت عن مقاس غير متوفر، ثم سألت عن سعر ولم تكمل، ثم اشترت. هنا تصبح الخطوة التالية واضحة: عندما يعود ذلك المقاس، أخبرها. وقبل ذلك، سؤال واحد يوضح سبب التوقف: هل كان السعر أم المقاس أم التوقيت؟',
        'In a CRM you see the same page: asked about an unavailable size, then asked a price and did not complete, then bought. Now the next step is obvious: when that size returns, tell her. And before that, one question clarifies why she stopped: was it the price, the size, or the timing?',
      ) },

      { h: c('متى يكفيك سجل الطلبات، ومتى تحتاج CRM', 'When a log is enough, and when you need a CRM') },
      { p: c(
        'لا تشترِ أداة لأنها مشهورة. استخدم قواعد القرار التالية، وطبّقها على وضعك الحالي لا على ما تتمناه بعد سنة. القاعدة الأولى توفّر عليك اشتراكًا لن تستخدمه، والثانية توفّر عليك سنة من الطلبات الضائعة.',
        'Do not buy a tool because it is famous. Use the decision rules below, and apply them to your situation today, not to what you hope for in a year. The first rule saves you a subscription you will not use, the second saves you a year of lost orders.',
      ) },
      { ul: [
        c('يكفيك السجل إن كان معظم من يشتري منك يشتري مرة واحدة، وعددهم في الشهر قليل تعرفهم بالاسم.', 'A log is enough if most of your buyers buy once, and there are few enough each month that you know them by name.'),
        c('يكفيك إن كنت وحدك من يرد، ولا أحد يشاركك المحادثات.', 'It is enough if you alone reply and nobody shares the conversations with you.'),
        c('تحتاج CRM إن كان العميل العائد جزءًا حقيقيًا من مبيعاتك، لا استثناء.', 'You need a CRM if returning customers are a real part of your sales, not an exception.'),
        c('تحتاج CRM إن كان أكثر من شخص يرد، وحدث أن ردّ اثنان على العميل نفسه أو لم يرد أحد.', 'You need one if more than one person replies, and it has happened that two replied to the same customer or nobody did.'),
        c('تحتاج CRM إن كنت تنسى متابعة من سأل ولم يشتر، أو تكتشف ذلك بعد أسبوع.', 'You need one if you forget to follow up with people who asked and did not buy, or discover it a week later.'),
      ] },
      { p: c(
        'قاعدة عملية: إن وجدت في القائمة الثانية ثلاثة بنود أو أكثر، فأنت تحتاج CRM، أو على الأقل تنظيمًا يشبهه. وإن لم تجد إلا بندًا واحدًا، فأصلح السجل أولًا، لأن CRM مليئًا ببيانات ناقصة أسوأ من سجل صغير صحيح، ولأن الأداة لا تُنشئ عادة لم تكن موجودة.',
        'A practical rule: if you found three or more items in the second list, you need a CRM, or at least an order system that behaves like one. If you found only one, fix the log first, because a CRM full of incomplete data is worse than a small correct log, and a tool does not create a habit that was never there.',
      ) },

      { h: c('أخطاء شائعة وكيف تصلحها', 'Common mistakes and how to fix them') },
      { ul: [
        c('شراء CRM قبل ترتيب السجل: تنتقل الفوضى إلى أداة أنيقة. الإصلاح: نظّف آخر شهرين من الطلبات أولًا، وانقل ما هو صحيح فقط.', 'Buying a CRM before tidying the log: the mess moves into a nicer tool. Fix: clean up the last two months of orders first, and migrate only what is correct.'),
        c('سجل بلا عمود حالة: كل الصفوف تبدو متشابهة. الإصلاح: أضف عمود حالة بخيارات قليلة ثابتة، ولا تكتب فيه جملًا حرة.', 'A log with no status column: every row looks the same. Fix: add a status column with a few fixed options, and never type free sentences into it.'),
        c('الاسم بصيغ مختلفة: الاسم الأول مرة، والاسم مع الحرف الأول مرة، ورقم بلا اسم مرة. الإصلاح: اربط كل عميل برقم هاتف واحد، واعتبر الرقم هو المعرّف.', 'The name in different forms: first name once, first name plus initial once, a number with no name once. Fix: tie each customer to one phone number, and treat the number as the identifier.'),
        c('نظامان منفصلان: السجل في ملف، والمحادثات في الهاتف، والتحديث يدوي. الإصلاح: مكان واحد مرجع، وكل مكان آخر نسخة تُقرأ ولا تُعدَّل.', 'Two separate systems: the log in a file, the chats on a phone, updating by hand. Fix: one place is the source of truth, every other place is a copy that is read, not edited.'),
        c('CRM يُستخدم كدفتر عناوين: أسماء بلا تاريخ ولا خطوة تالية. الإصلاح: لا تُنشئ صفحة عميل بلا سبب واضح للتواصل معه لاحقًا.', 'A CRM used as an address book: names with no history and no next step. Fix: do not create a customer page without a clear reason to contact them later.'),
        c('المتابعة في الذاكرة: أخطرها وأكثرها شيوعًا. الإصلاح: موعد مكتوب أو تذكير، وقائمة يومية قصيرة تُقرأ لا تُتذكَّر.', 'Follow-up kept in memory: the most dangerous and the most common. Fix: a written date or a reminder, and a short daily list that is read rather than remembered.'),
      ] },

      { h: c('كيف تربط الاثنين بأي أداة', 'How to link the two with any tool') },
      { ol: [
        c('اختر معرّفًا واحدًا لكل عميل، والأفضل رقم الهاتف لأنه لا يتغيّر كثيرًا.', 'Pick one identifier per customer, ideally the phone number because it rarely changes.'),
        c('في سجل الطلبات، اجعل عمود العميل إلزاميًا، واكتب الرقم نفسه في كل مرة.', 'In the order log, make the customer column mandatory, and write the same number every time.'),
        c('أضف عمودين فقط: حالة الطلب، وموعد المتابعة التالي.', 'Add only two columns: order status, and next follow-up date.'),
        c('افصل حالة الطلب (جديد، مؤكد، شُحن، سُلِّم) عن حالة المحادثة (ينتظر ردنا، ينتظر العميل، مغلقة)، فالأولى عن الشحنة والثانية عن الحوار.', 'Keep order status (new, confirmed, shipped, delivered) separate from conversation status (waiting for us, waiting for the customer, closed), because one is about the parcel and the other about the conversation.'),
        c('أنشئ صفحة قصيرة لكل عميل لا تكرر البيانات، بل تجمع روابط طلباته وملاحظة أخيرة.', 'Create a short page per customer that does not duplicate data but collects links to their orders and one latest note.'),
        c('اجعل مراجعة أسبوعية ثابتة: من ينتظر ردًا، ومن ينتظر متابعة، وما أكثر سؤال تكرر.', 'Set a fixed weekly review: who is waiting for a reply, who is waiting for a follow-up, and which question repeated most.'),
      ] },
      { p: c(
        'هذه الخطوات تعمل على جدول بسيط، ويعمل بعضها على دفتر إن كان الحجم صغيرًا. المهم أن يكون المعرّف واحدًا وأن يُكتب تاريخ المتابعة، لأن أكثر ما يفشل في المتاجر الصغيرة ليس اختيار الأداة، بل أن المعلومة موجودة ولا أحد يراها في اللحظة المناسبة.',
        'These steps work on a simple sheet, and some of them work in a notebook if the volume is small. What matters is one identifier and a written follow-up date, because what fails most in small stores is not the choice of tool, but that the information exists and nobody sees it at the right moment.',
      ) },

      { h: c('الحقول الدنيا ونموذج تقدر تنسخه', 'The minimum fields, and a template you can copy') },
      { p: c(
        'لا تحتاج عشرين حقلًا. الحقول الكثيرة تُهمَل، والحقل الذي لا يُملأ أسوأ من عدم وجوده لأنه يوهمك بأن لديك معلومة. ابدأ بالحد الأدنى الذي يجيب عن السؤالين معًا: ماذا بعنا، ومن اشترى.',
        'You do not need twenty fields. Many fields get abandoned, and a field that is never filled is worse than a missing one because it convinces you that you have information. Start with the minimum that answers both questions: what did we sell, and who bought.',
      ) },
      { ul: [
        c('بطاقة العميل: اسم واحد معتمد، ورقم هاتف.', 'Customer card: one canonical name, and one phone number.'),
        c('كيف وصل إليك: واتساب، إنستغرام، توصية، زيارة للمتجر.', 'How they reached you: WhatsApp, Instagram, a referral, a store visit.'),
        c('آخر تواصل، وملاحظة قصيرة عن نتيجته لا عن مضمونه.', 'Last contact, and a short note about its outcome rather than its content.'),
        c('الخطوة التالية وتاريخها، والمسؤول عنها.', 'The next step, its date, and who owns it.'),
        c('بطاقة الطلب: رقم الطلب وتاريخه، ورقم هاتف العميل.', 'Order card: order number and date, and the customer phone number.'),
        c('المنتج مع المقاس أو اللون أو الخيار، والكمية، والسعر المتفق عليه.', 'The product with size, color, or option, the quantity, and the agreed price.'),
        c('الحالة، وطريقة التسليم، وأي ملاحظة تُغني عن سؤال العميل مرة أخرى.', 'Status, delivery method, and any note that saves asking the customer again.'),
      ] },
      { p: c(
        'اطبع هذه القائمة أمامك أسبوعين، ثم احذف كل حقل لم تستخدمه وزد كل حقل احتجته ولم تجده.',
        'Keep this list in front of you for two weeks, then delete any field you never used and add any field you needed and did not have.',
      ) },

      { h: c('إذا حدث كذا فافعل كذا', 'If this happens, do that') },
      { ul: [
        c('إن اختلف رقم المبيعات في السجل عن الصندوق، فاعتبر الصندوق هو الحقيقة لحظة البيع، وحدّث السجل في اليوم نفسه، ثم ابحث عن سبب الفرق في آخر ثلاثة صفوف قبل أن تتهم أحدًا.', 'If the log total disagrees with the cash drawer, treat the drawer as the truth at the moment of sale, update the log the same day, then look for the cause in the last three rows before blaming anyone.'),
        c('إن تكرر سؤال العميل عن حالة طلبه، فالمشكلة في وضوح الحالة لا في العميل: أخبره بحالة طلبه في رسالة قصيرة عند كل تغيير.', 'If a customer keeps asking about their order status, the problem is status visibility, not the customer: send a short message at every change.'),
        c('إن وجدت عميلًا له أكثر من سجل، فادمج القديم في الأحدث واحتفظ برقم واحد، وانقل التاريخ القديم كملاحظة بدل حذفه.', 'If you find a customer with more than one record, merge the old into the newer, keep one number, and move the old history across as a note instead of deleting it.'),
        c('إن توقف الفريق عن تعبئة الـ CRM، فقلّل الحقول إلى ثلاثة، وذكّر بأن الهدف سرعة الرد لا المراقبة، لأن الشعور بالمراقبة هو ما يوقف التعبئة.', 'If the team stops filling in the CRM, cut the fields to three and remind them the goal is faster replies, not surveillance, because feeling watched is what stops data entry.'),
        c('إن كانت المتابعة تُنسى دائمًا، فاجعلها مهمة صباحية بعشر دقائق، لا وعدًا.', 'If follow-up is always forgotten, make it a ten minute morning task, not a promise.'),
        c('إن لم تعرف من أين تبدأ، فخذ آخر ثلاثين طلبًا فقط وحوّلها إلى الشكل الجديد. الشهر القادم سيُبنى على هذا الأساس وحده.', 'If you do not know where to start, take only the last thirty orders and convert them to the new shape. Next month will build on that foundation alone.'),
      ] },

      { h: c('أين يقع FIHRIST من هذا كله', 'Where FIHRIST fits into this') },
      { p: c(
        'كل ما سبق يمكن تنفيذه بجدول ودفتر وانضباط. الحاجة إلى أداة تظهر عندما يصبح الربط اليدوي أبطأ من البيع نفسه. هنا يدخل FIHRIST كأداة لا كبديل عن التنظيم: يجمع محادثات واتساب وماسنجر وإنستغرام والبريد وشات الموقع في صندوق واحد، ويربط كل محادثة بسجل العميل والمنتج والطلب، ويتيح تعيين مسؤول وحالة لكل محادثة، ويضبط تذكيرات وقواعد متابعة يمكن إيقافها، مع صلاحيات لكل عضو في الفريق. يعمل بالعربية والإنجليزية، والقنوات المتاحة تعتمد على ما تربطه أنت.',
        'All of the above can be done with a sheet, a notebook, and discipline. The need for a tool appears when linking by hand becomes slower than selling. That is where FIHRIST comes in, as a tool and not a substitute for organization: it brings WhatsApp, Messenger, Instagram, email, and web chat conversations into one inbox, links each conversation to the customer, product, and order record, lets you assign an owner and a status to each conversation, and sets reminders and follow-up rules that can be turned off, with permissions per team member. It works in Arabic and English, and the channels available depend on what you connect.',
      ) },
      { p: c(
        'لكن إن كنت تعمل وحدك بثلاثين طلبًا في الشهر، فقد يكفيك سجل نظيف وموعد متابعة مكتوب. ابدأ بالخطوات، ثم اختر الأداة التي تقلّل العمل اليدوي الذي تعاني منه فعلًا، لا العمل اليدوي الذي يزعجك في نظرية.',
        'But if you work alone with thirty orders a month, a clean log and a written follow-up date may be enough. Start with the steps, then choose the tool that reduces the manual work you actually suffer from, not the manual work that bothers you in theory.',
      ) },
    ],
    faq: [
      {
        q: c('هل الـ CRM هو نفسه سجل الطلبات؟', 'Is a CRM the same as an order log?'),
        a: c(
          'لا. سجل الطلبات يحفظ المعاملة، والـ CRM يحفظ العميل وتاريخه والخطوة التالية معه. كثير من الأنظمة تجمع الاثنين في شاشة واحدة، لكن الفرق في السؤال الذي يجيب عنه كل منهما يبقى مهمًا عند الاختيار، لأن الأداة التي تجيب عن سؤال لا تحتاجه لن تُستخدم.',
          'No. An order log keeps the transaction, a CRM keeps the customer, their history, and the next step with them. Many systems combine both in one screen, but the difference in the question each answers still matters when choosing, because a tool that answers a question you do not have will not get used.',
        ),
      },
      {
        q: c('هل أحتاج CRM لمتجر صغير جدًا؟', 'Does a very small store need a CRM?'),
        a: c(
          'ليس بالضرورة. إن كان معظم عملائك يشترون مرة واحدة وكنت وحدك من يرد، فسجل طلبات منظم فيه عمود حالة وموعد متابعة يكفي تمامًا. الحاجة تظهر عندما يصبح العميل العائد جزءًا من مبيعاتك، أو عندما يشاركك أحد في الرد ويحدث تكرار أو صمت.',
          'Not necessarily. If most of your customers buy once and you are the only one replying, a tidy order log with a status column and a follow-up date is entirely enough. The need appears when returning customers become part of your sales, or when someone shares the replying and duplication or silence starts to happen.',
        ),
      },
      {
        q: c('ما أول حقل أضيفه إلى جدول الطلبات؟', 'What is the first field to add to an order sheet?'),
        a: c(
          'عمود الحالة بخيارات ثابتة: جديد، مؤكد، شُحن، سُلِّم. هو أرخص إضافة وأكثرها فائدة، لأنه يحوّل الجدول من أرشيف إلى قائمة عمل تخبرك بما يجب تجهيزه اليوم. أضف بعده موعد المتابعة، ثم توقف، فالحقول الكثيرة تُهمَل.',
          'A status column with fixed options: new, confirmed, shipped, delivered. It is the cheapest addition and the most useful, because it turns the sheet from an archive into a work list that tells you what to prepare today. Add the follow-up date after it, then stop, because too many fields get abandoned.',
        ),
      },
      {
        q: c('كيف أربط الطلب بالعميل دون نظام كبير؟', 'How do I link orders to customers without a big system?'),
        a: c(
          'استخدم رقم الهاتف كمعرّف واحد، واكتبه في كل صف بنفس الصيغة، ثم أضف عمودين: موعد المتابعة والمسؤول. بذلك تستطيع أن ترى تاريخ شخص واحد بفرز الصفوف على رقمه، وهذا وحده يحل أكثر مشاكل التشتت في المتاجر الصغيرة.',
          'Use the phone number as a single identifier, write it in the same format in every row, then add two columns: follow-up date and owner. That lets you see one person history by sorting rows on their number, and that alone solves most of the scatter problem in small stores.',
        ),
      },
      {
        q: c('هل يمكن أن يكون الجدول نفسه CRM؟', 'Can a spreadsheet itself be a CRM?'),
        a: c(
          'يمكن أن يكون بداية، بشرط أن تجمع فيه تاريخ التواصل والخطوة التالية لا الطلبات فقط، وأن تفتحه كل يوم. لكن الجداول تصعب عندما يعدّلها أكثر من شخص في الوقت نفسه، ويصعب فيها رؤية محادثة العميل بجانب طلبه.',
          'It can be a start, provided you collect contact history and the next step in it, not only orders, and you open it every day. But sheets get hard when more than one person edits them at the same time, and it is hard to see a customer conversation beside their order.',
        ),
      },
    ],
    related: ['follow-up-customers-who-went-quiet', 'reply-to-customers-faster-unified-inbox'],
    solution: 'sales-crm-for-stores',
  },

  'reply-to-customers-faster-unified-inbox': {
    date: '2026-11-15',
    minutes: 9,
    title: c('كيف ترد على العملاء أسرع بصندوق موحد | FIHRIST', 'Reply to Customers Faster with a Unified Inbox | FIHRIST'),
    description: c(
      'كيف يقلل الصندوق الموحد زمن الرد على العملاء عبر واتساب وماسنجر وإنستغرام والبريد، وما الذي تنظمه قبل أن تبدأ.',
      'How a unified inbox cuts reply time across WhatsApp, Messenger, Instagram, and email, and what to organize before you start.',
    ),
    h1: c('كيف ترد على العملاء أسرع', 'How to reply to customers faster'),
    lede: c(
      'سرعة الرد غالبًا تحسم البيع، ليس لأن العميل يستعجل دائمًا، بل لأنه يكتب لثلاثة متاجر في الدقيقة نفسها ويميل لمن يجيبه أولًا بجواب مفيد. المشكلة أن جزءًا كبيرًا من وقتك لا يذهب في الكتابة، بل في البحث والتنقل والتأكد. هذا الدليل يفكك الرد إلى خطوات، ثم يقصّر كل خطوة.',
      'Reply speed often decides the sale, not because the customer is always in a hurry, but because they message three stores in the same minute and lean toward whoever answers first with something useful. The problem is that a large part of your time goes not into typing, but into searching, switching, and checking. This guide breaks a reply into steps, then shortens each step.',
    ),
    body: [
      { h: c('سرعة الرد ليست سرعة الكتابة', 'Reply speed is not typing speed') },
      { p: c(
        'عندما نقول إن متجرًا يرد بسرعة، لا نعني أن صاحبه يكتب بسرعة. نعني أن الطريق بين وصول الرسالة وظهور الرد قصير. هذا الطريق فيه خطوات صغيرة متكررة: تفتح التطبيق، ترى من كتب، تحاول أن تتذكر من هو، تبحث عن طلبه السابق، تسأل زميلًا هل رد، تجمع الجواب، ثم تكتب.',
        'When we say a store replies fast, we do not mean its owner types fast. We mean the path between a message arriving and a reply appearing is short. That path has small repeated steps: open the app, see who wrote, try to recall who they are, look up their previous order, ask a colleague whether they replied, assemble the answer, then type.',
      ) },
      { p: c(
        'كل خطوة من هذه الخطوات لا تستغرق أكثر من دقيقة، ولهذا لا تشعر بها. لكنها تتكرر مع كل رسالة. لو كانت الرسالة الواحدة تكلّفك خمس دقائق من التحضير ودقيقة من الكتابة، فأنت لا ترد ببطء، أنت تحضّر ببطء. وتقصير التحضير هو ما يغيّر الإحساس بالسرعة عند العميل.',
        'None of these steps takes more than a minute, which is why you do not notice them. But they repeat with every message. If a single message costs you five minutes of preparation and one minute of typing, you are not slow at replying, you are slow at preparing. Shortening the preparation is what changes the customer perception of speed.',
      ) },

      { h: c('أين يضيع الوقت فعلًا', 'Where the time really goes') },
      { p: c(
        'مثال محسوب صغير، بلا أي أرقام تدّعي واقعية عند غيرك. تخيّل أنك تستقبل عشرين رسالة في يوم. في كل مرة تتوقف عن العمل الحالي لتفتح تطبيقًا آخر، وتعود بعدها إلى ما كنت تفعله. التوقف نفسه، لا الرد، هو التكلفة الخفية: كل عودة تحتاج دقيقة لاستعادة التركيز. عشرون توقفًا يعني عشرين دقيقة من التركيز المفقود، وهذا في يوم هادئ.',
        'A small worked example, claiming no realism for anyone else situation. Imagine you receive twenty messages in a day. Each time you stop current work to open another app, then return to what you were doing. The interruption itself, not the reply, is the hidden cost: every return needs a minute to regain focus. Twenty interruptions means twenty minutes of lost focus, and that is on a quiet day.',
      ) },
      { ul: [
        c('التنقل بين التطبيقات لمعرفة من كتب، ونسيان قناة كاملة لأنها خارج العين.', 'Switching between apps to see who wrote, and forgetting a whole channel because it is out of sight.'),
        c('البحث عن معلومات العميل أو طلبه السابق قبل أن تجيب، وهذا البحث هو أطول جزء عادة.', 'Looking up the customer or their previous order before answering, and this lookup is usually the longest part.'),
        c('عدم معرفة هل رد زميلك أم لا، فتسأله، فيرد بأنه رد، فتضيع رسالتان على سؤال واحد.', 'Not knowing whether a teammate replied, so you ask them, they say they did, and two messages are wasted on one question.'),
        c('كتابة الإجابة نفسها لأسئلة متكررة، مع اختلاف بسيط في الصياغة كل مرة.', 'Retyping the same answer to repeated questions, with a slight change in wording each time.'),
        c('الرد في وقت غير مناسب لأن الرسالة وصلت في لحظة انشغال ثم نُسيت.', 'Replying at the wrong time because the message arrived at a busy moment and was then forgotten.'),
      ] },
      { p: c(
        'لاحظ أن بندًا واحدًا فقط من هذه البنود يتعلق بالكتابة. الباقي كله تنظيم. لهذا فإن شراء تطبيق أسرع لا يحل شيئًا إن كانت المعلومة موزعة على ثلاثة أماكن: أنت تنقل البطء من مكان إلى آخر.',
        'Note that only one of these items relates to typing. The rest is organization. That is why buying a faster app solves nothing if the information is split across three places: you are moving the slowness from one place to another.',
      ) },

      { h: c('الخطوة 1: اجمع القنوات في مكان واحد', 'Step 1: bring the channels into one place') },
      { p: c(
        'عدد القنوات التي تفتحها كل صباح هو عدد المرات التي قد تنسى فيها واحدة. صندوق موحد يعرض كل الرسائل في قائمة واحدة، مرتبة بالأحدث أو بما ينتظر ردًا، فتبدأ يومك بنافذة واحدة لا بخمس. الفكرة ليست تقنية، الفكرة أن تصبح كل الرسائل في مجال نظرك في اللحظة نفسها.',
        'The number of channels you open each morning is the number of chances to forget one. A unified inbox shows all messages in one list, sorted by newest or by what is waiting for a reply, so you start your day in one window instead of five. The idea is not technical, it is that every message becomes visible to you at the same moment.',
      ) },
      { p: c(
        'إن لم يكن عندك صندوق موحد، فابدأ بحل وسط: اجعل قناة واحدة هي القناة الرئيسية، واكتب في وصف حسابك على القنوات الأخرى أن الطلبات تُستكمل هناك، ثم راجع القنوات الثانوية في وقتين ثابتين كل يوم. هذا أقل كفاءة من صندوق موحد، لكنه أفضل كثيرًا من مراجعة عشوائية.',
        'If you do not have a unified inbox, start with a middle solution: make one channel the main one, state in your profile on the other channels that orders are completed there, then check the secondary channels at two fixed times a day. This is less efficient than a unified inbox, but far better than checking at random.',
      ) },

      { h: c('الخطوة 2: اعرض سياق العميل بجانب الرسالة', 'Step 2: show customer context beside the message') },
      { p: c(
        'أبطأ جزء في الرد هو السؤال الصامت: من هذا؟ وماذا طلب سابقًا؟ إن ظهر الاسم وطلباته السابقة بجانب الرسالة، يتحول الرد من بحث إلى كتابة فقط. وهذا يقلّل أيضًا الأخطاء، لأنك لا تعتذر لعميل عن منتج اشتراه بالفعل ولا تكرر عليه سؤالًا أجاب عنه.',
        'The slowest part of replying is the silent question: who is this, and what did they order before? If the name and past orders appear beside the message, replying becomes writing instead of searching. This also reduces mistakes, because you do not apologize to a customer for an item they already bought, nor ask again something they answered.',
      ) },
      { p: c(
        'أقل ما تحتاجه بجانب الرسالة ثلاثة أشياء: الاسم، وآخر طلب إن وُجد، وملاحظة قصيرة من آخر تواصل. بهذه الثلاثة تكتب ردًّا مناسبًا في معظم الحالات. أي معلومة إضافية جميلة، لكنها ليست شرطًا للبدء.',
        'The minimum you need beside a message is three things: the name, the last order if any, and a short note from the last contact. With those three you write a fitting reply in most cases. Any extra information is nice, but it is not a condition to start.',
      ) },

      { h: c('الخطوة 3: عيّن مسؤولًا وحالة لكل محادثة', 'Step 3: assign an owner and a status to every conversation') },
      { p: c(
        'عندما يكون لكل محادثة اسم، يختفي سؤال "هل رد أحد؟" ويختفي معه أخطر شكل من أشكال الخطأ: أن يظن اثنان أن الآخر رد، فلا يرد أحد. وتستطيع أن ترى بسرعة ما ينتظر ردًا ومن عليه، بدل أن تفتح كل محادثة لتكتشف ذلك.',
        'When each conversation has a name on it, the question "did anyone reply?" disappears, and with it the worst kind of mistake: two people each assuming the other replied, so nobody does. You can also see quickly what is waiting for a reply and who owns it, instead of opening every conversation to find out.',
      ) },
      { ul: [
        c('حالة "ينتظر ردنا": هي قائمتك الأولى في الصباح، وهي المكان الذي تُقاس فيه السرعة فعلًا.', 'Status "waiting for us": this is your first list in the morning, and it is where speed is actually measured.'),
        c('حالة "ينتظر العميل": تحتاج مراجعة مرة واحدة يوميًا، لا مراقبة مستمرة.', 'Status "waiting for the customer": needs one check a day, not constant watching.'),
        c('حالة "مغلقة": محادثة انتهت بنتيجة واضحة، طلب أو رفض أو تحويل. لا تُغلق بلا نتيجة.', 'Status "closed": a conversation that ended with a clear outcome, an order, a no, or a handover. Do not close without an outcome.'),
        c('حالة "يحتاج قرارًا": العميل سأل ما لا تملك الإجابة عنه، فتُحوَّل إلى من يملكها فورًا.', 'Status "needs a decision": the customer asked something you cannot answer, so it goes immediately to whoever can.'),
      ] },
      { p: c(
        'قاعدة بسيطة للفريق: لا تُغلق محادثة وأنت لا تعرف نتيجتها. الإغلاق بلا نتيجة يجعل الأرقام كاذبة، ويجعل المحادثة تعود بعد أسبوع كأنها جديدة، فيسأل العميل مرة أخرى عن الشيء نفسه ويتلقى ردًّا مختلفًا.',
        'A simple team rule: do not close a conversation whose outcome you do not know. Closing without an outcome makes the numbers false and makes the conversation return a week later as if new, so the customer asks the same thing again and gets a different answer.',
      ) },

      { h: c('الخطوة 4: جهّز ردودًا متكررة، لا ردودًا آلية', 'Step 4: prepare repeated replies, not automatic ones') },
      { p: c(
        'اجمع الأسئلة التي تتكرر أسبوعيًا واكتب لكل منها إجابة جيدة مرة واحدة، ثم عدّلها بحسب العميل بدل كتابتها من الصفر. الفرق بين القالب والرد الآلي أن القالب نقطة بداية تكتبها أنت، والرد الآلي جواب يُرسَل بلا قراءة. الأول يسرّع، والثاني يُشعر العميل أنه يتحدث إلى جدار.',
        'Collect the questions that repeat weekly and write one good answer to each, then adapt it per customer instead of writing from scratch. The difference between a template and an automatic reply is that a template is a starting point you write from, while an automatic reply is sent without reading. The first speeds you up, the second makes the customer feel they are talking to a wall.',
      ) },
      { p: c(
        'الأسئلة التي تستحق قالبًا عادة خمسة: السعر النهائي شاملة التوصيل، التوفر بالمقاس أو اللون، مدة التوصيل، طرق الدفع، وسياسة الاستبدال. اكتب لكل واحد جملتين فقط. الجملة الطويلة تُقرأ نصفها، والقصيرة تُقرأ كاملة.',
        'The questions that deserve a template are usually five: the final price including delivery, availability in a size or color, delivery time, payment methods, and the exchange policy. Write only two sentences for each. A long message gets half read, a short one gets read fully.',
      ) },
      { ul: [
        c('السعر: "سعر القطعة كذا، والتوصيل كذا، فالإجمالي كذا. أحتاجه بالإسم والعنوان لو تحب أجهزه."', 'Price: "The item is X, delivery is Y, so the total is Z. Send me the name and address if you would like me to prepare it."'),
        c('التوفر: "متوفر بالمقاس المطلوب الآن، والكمية محدودة. هل أحجزه لك؟"', 'Availability: "It is available in the size you asked about now, and the quantity is limited. Shall I hold it for you?"'),
        c('التوصيل: "التوصيل داخل المدينة يستغرق عادة كذا يوم عمل، وخارجها كذا. أرسل لي العنوان وأتحقق لك بدقة."', 'Delivery: "Delivery inside the city usually takes X working days, outside it Y. Send me the address and I will check precisely."'),
        c('عدم التوفر: "هذا المقاس غير متوفر حاليًا. عندي بديل قريب أو أخبرك عند وصوله، أيهما تفضل؟"', 'Out of stock: "This size is not available right now. I have a close alternative or I can tell you when it arrives, which do you prefer?"'),
      ] },
      { p: c(
        'عند استخدام قالب، غيّر أول جملة على الأقل لتكون خاصة بهذا العميل. جملة واحدة مرتبطة بما قاله تكفي ليعرف أنك قرأت رسالته، وهذا يمنع الإحساس بالرد الجاهز أكثر من أي شيء آخر.',
        'When using a template, change at least the first sentence so it is specific to this customer. One sentence tied to what they said is enough for them to know you read their message, and that prevents the feeling of a canned reply more than anything else.',
      ) },

      { h: c('الخطوة 5: ضع هدفًا واقعيًا لزمن الرد وقِسه', 'Step 5: set a realistic reply-time goal and measure it') },
      { p: c(
        'اختر هدفًا يناسب طبيعة منتجك، لا هدفًا تُعجب به في مقال. منتج يُشترى بعد تفكير طويل قد يحتمل ردًّا بعد ساعتين، ومنتج يُطلب في نفس اللحظة قد لا يحتمله. المهم أن يكون الهدف مكتوبًا ومعروفًا لكل من يرد، وأن تحدد ساعات العمل التي يُقاس فيها.',
        'Pick a goal that suits your product, not one you admire in an article. An item bought after long thought may tolerate a reply two hours later, an item ordered on impulse may not. What matters is that the goal is written, known to everyone who replies, and that you define the working hours it is measured in.',
      ) },
      { p: c(
        'ثم قِس شيئًا واحدًا فقط في البداية: كم محادثة مرّ عليها يوم عمل بلا رد. لا تقِس متوسط الزمن، لأن المتوسط يخفي الحالات السيئة التي تضيّع العملاء. الحالة التي انتظرت يومين أهم من عشر حالات رُدّ عليها في دقيقة.',
        'Then measure only one thing at first: how many conversations went a working day without a reply. Do not measure the average, because an average hides the bad cases that lose customers. The case that waited two days matters more than ten cases answered in a minute.',
      ) },
      { ol: [
        c('اكتب الهدف في مكان يراه الفريق، مع ساعات العمل.', 'Write the goal where the team can see it, along with the working hours.'),
        c('راجع أسبوعيًا قائمة "ينتظر ردنا" واستخرج منها ما تجاوز الهدف.', 'Review the "waiting for us" list weekly and pull out what exceeded the goal.'),
        c('اسأل عن السبب لا عن المسؤول: نقص معلومة، أو انشغال في وقت الذروة، أو رسالة وصلت خارج ساعات العمل.', 'Ask about the cause, not the culprit: missing information, a busy peak, or a message that arrived outside working hours.'),
        c('أصلح سببًا واحدًا كل أسبوع، ولا تحاول إصلاح كل شيء مرة واحدة.', 'Fix one cause each week, and do not try to fix everything at once.'),
      ] },
      { p: c(
        'هدف غير واقعي أسوأ من عدم وجود هدف، لأنه يجعل الفريق يتوقف عن القياس أو يبدأ في إخفاء الحالات المتأخرة. اختر هدفًا تستطيع تحقيقه في أسبوع عادي، ثم شدّه تدريجيًا بعد أن يثبت.',
        'An unrealistic goal is worse than no goal, because it makes the team stop measuring or start hiding the late cases. Choose a goal you can meet in an ordinary week, then tighten it gradually once it holds.',
      ) },

      { h: c('الخطوة 6: وزّع العمل حين يكون هناك أكثر من شخص', 'Step 6: share the load when there is more than one person') },
      { p: c(
        'وجود أكثر من شخص لا يسرّع الرد تلقائيًا، وقد يبطئه. القاعدة أن كل محادثة يجب أن يكون لها مسؤول واحد في أي لحظة، حتى لو تغيّر المسؤول بعد ذلك. عندما يكون المسؤول مشتركًا، لا يكون هناك مسؤول.',
        'Having more than one person does not automatically speed up replies, and can slow them down. The rule is that every conversation must have one owner at any moment, even if the owner changes later. When the owner is shared, there is no owner.',
      ) },
      { ul: [
        c('قسّم بالقناة أو بنوع السؤال، لا بالمزاج: من يرد على الاستفسارات، ومن يتابع الطلبات المؤكدة.', 'Split by channel or question type, not by mood: who answers inquiries, who follows up confirmed orders.'),
        c('أعطِ كل عضو الصلاحيات التي يحتاجها فقط، فلا يرى من يحتاج بيانات الأسعار بيانات العملاء كلها.', 'Give each member only the permissions they need, so someone who needs pricing data does not see all customer data.'),
        c('اجعل من يرد قادرًا على رؤية التوفر والسعر بنفسه، فكل سؤال يذهب لشخص آخر يصبح تأخيرًا.', 'Make the person replying able to see availability and price themselves, since every question routed to someone else becomes a delay.'),
      ] },
      { p: c(
        'وضوح الصلاحيات ليس إجراءً إداريًا فقط. إن لم يستطع من يرد رؤية المعلومة، فسيذهب ليسأل، وسينتظر، وسيتأخر الرد. الصلاحية هي جزء من سرعة الرد، لأنها تحدد هل الجواب على بعد نقرة أم على بعد محادثة داخلية.',
        'Clear permissions are not only an administrative matter. If the person replying cannot see the information, they will go and ask, they will wait, and the reply will be late. Permissions are part of reply speed, because they determine whether the answer is one click away or one internal conversation away.',
      ) },

      { h: c('أخطاء شائعة تعطّل السرعة', 'Common mistakes that block speed') },
      { ul: [
        c('الرد على كل رسالة فورًا: يجعلك متاحًا دائمًا، فتتوقف عن العمل الحقيقي. الأفضل أوقات مراجعة ثابتة، ومعالجة قائمة الانتظار بالترتيب.', 'Replying to every message instantly: it makes you permanently available, so real work stops. Fixed review times and working the queue in order are better.'),
        c('الاعتماد على الإشعارات: الإشعار يقطعك، ثم تنسى الرسالة بعد أن تُغلق الإشعار. العمل من قائمة أفضل من العمل من إشعار.', 'Relying on notifications: a notification interrupts you, then you forget the message once you dismiss it. Working from a list beats working from a notification.'),
        c('رد بلا سؤال: "تم" أو "أبشر" تُنهي رسالتك ولا تنقل الحوار خطوة. كل رد جيد يحتوي سؤالًا واحدًا أو معلومة واحدة جديدة.', 'A reply with no question: "done" or "sure" ends your message without moving the conversation. Every good reply contains one question or one new piece of information.'),
        c('الرد الآلي على كل شيء: يوقف العميل عند أول خطوة حين يريد جوابًا محددًا. اجعله يوضح الخطوة التالية فقط.', 'Automatic replies to everything: they stop the customer at the first step when they want a specific answer. Keep it to clarifying the next step only.'),
        c('قنوات كثيرة بلا وقت مراجعة: القناة التي لا تُراجع هي قناة لا تملكها.', 'Many channels with no review time: a channel you do not review is a channel you do not own.'),
        c('إغلاق المحادثة بعد إرسال السعر: أكثر اللحظات حساسية هي ما بعد السعر، وهي المكان الذي تذهب إليه المتابعة.', 'Closing a conversation after sending a price: the most sensitive moment is right after a price, and that is where follow-up belongs.'),
      ] },

      { h: c('إذا حدث كذا فافعل كذا', 'If this happens, do that') },
      { ul: [
        c('إن كان العميل يكتب على قناة لا تراقبها، فأضفها إلى وقت المراجعة أو أغلقها رسميًا واذكر البديل في وصفها.', 'If customers write on a channel you do not watch, add it to review time or close it officially and state the alternative in its profile.'),
        c('إن وصلت رسالة قبل النوم، فأرسل سطرًا واحدًا يحدد الوقت: "شفت رسالتك، أرد عليك بالتفصيل صباحًا". هذا يهدئ العميل أكثر من رد ناقص متعب.', 'If a message arrives at bedtime, send one line fixing the time: "I saw your message, I will reply in detail in the morning." This calms the customer more than a tired, incomplete reply.'),
        c('إن تكرر سؤال واحد كثيرًا، فالخطأ في مكان آخر: أضف الجواب إلى وصف المنتج أو إلى الردود الجاهزة.', 'If one question repeats a lot, the error is elsewhere: add the answer to the product description or the ready replies.'),
        c('إن ظل عميل يسأل عن حالة طلبه، فأرسل تحديثًا عند كل تغيير بدون أن يُطلب منك.', 'If a customer keeps asking about order status, send an update at every change without being asked.'),
        c('إن كان الرد يتأخر في وقت ذروة معروف، فحدد من يترك مهمته ويغطي الرسائل في تلك الساعة فقط.', 'If replies lag at a known peak time, assign who leaves their task to cover messages for that hour only.'),
        c('إن كنت تنسى الرد بعد الانشغال، فاجعل لكل رسالة حالة "ينتظر ردنا" حتى تُغلق برد أو تحويل.', 'If you forget a reply after getting busy, give every message the status "waiting for us" until it is closed by a reply or a handover.'),
      ] },

      { h: c('قائمة سريعة قبل أن تبدأ', 'A short checklist before you start') },
      { ol: [
        c('اكتب قائمة بالقنوات التي يراسلك عليها العملاء فعلًا، وهل تُراجع كلها أم بعضها يُنسى.', 'List the channels customers actually use to reach you, and whether all are reviewed or some are forgotten.'),
        c('حدّد وقتين ثابتين للمراجعة في يوم العمل، حتى لو لم تجمع القنوات بعد.', 'Set two fixed review times in the working day, even if you have not gathered the channels yet.'),
        c('اكتب خمسة قوالب قصيرة للأسئلة المتكررة، بجملتين لكل قالب.', 'Write five short templates for repeated questions, two sentences each.'),
        c('أضف لكل محادثة مسؤولًا وحالة، وابدأ بقائمة "ينتظر ردنا".', 'Add an owner and a status to every conversation, and start with the "waiting for us" list.'),
        c('اختر هدفًا واحدًا لزمن الرد، وقِس عدد الحالات التي تجاوزته أسبوعيًا.', 'Choose one reply-time goal, and measure weekly how many cases exceeded it.'),
        c('راجع بعد شهر: أي خطوة أضافت وقتًا بلا فائدة؟ احذفها.', 'Review after a month: which step added time without benefit? Remove it.'),
      ] },

      { h: c('كيف يساعد FIHRIST هنا', 'How FIHRIST helps here') },
      { p: c(
        'ما سبق يمكن تنفيذه يدويًا، لكن التنسيق اليدوي بين قناة وسجل ومحادثة يصبح أبطأ من الرد نفسه عندما تكثر الرسائل. هنا يأتي دور FIHRIST كأداة: يجمع واتساب وماسنجر وإنستغرام والبريد وشات الموقع في صندوق واحد، ويربط كل محادثة بسجل العميل والمنتج والطلب، ويتيح تعيين مسؤول وحالة لكل محادثة، ويضبط تذكيرات وقواعد متابعة يمكن إيقافها، مع صلاحيات لكل عضو في الفريق. يعمل بالعربية والإنجليزية، والقنوات المتاحة تعتمد على ما تربطه أنت.',
        'The above can be done by hand, but coordinating manually between a channel, a record, and a conversation becomes slower than the reply itself when messages pile up. That is where FIHRIST comes in as a tool: it brings WhatsApp, Messenger, Instagram, email, and web chat into one inbox, links each conversation to the customer, product, and order record, lets you assign an owner and a status to each conversation, and sets reminders and follow-up rules that can be turned off, with permissions per team member. It works in Arabic and English, and the channels available depend on what you connect.',
      ) },
      { p: c(
        'ابدأ بالخطوات أولًا: وقتا المراجعة، والقوالب الخمسة، وقائمة "ينتظر ردنا". هذه الثلاثة تعمل بلا أي أداة، وهي التي تصنع الفرق في الأسبوع الأول. الأداة تأتي بعدها لتقلل العمل اليدوي، لا لتُنشئ عادة لم تكن موجودة.',
        'Start with the steps first: the two review times, the five templates, and the "waiting for us" list. Those three work with no tool at all, and they are what makes the difference in the first week. The tool comes after them to reduce manual work, not to create a habit that was never there.',
      ) },
    ],
    faq: [
      {
        q: c('هل الصندوق الموحد يرد على العملاء بدلًا مني؟', 'Does a unified inbox reply to customers for me?'),
        a: c(
          'لا، هو يجمع الرسائل ويضع سياق العميل بجانبها ليصبح ردك أسرع وأدق. الرد يبقى منك. وهناك أدوات فيها مساعد يجيب من بيانات المتجر حين تفعّله، لكنه يبقى تحت إشراف الفريق الذي يستطيع التدخل في أي محادثة.',
          'No, it gathers messages and puts the customer context beside them so your reply is faster and more accurate. The reply is still yours. Some tools include an assistant that answers from store data when you enable it, but it stays under the team supervision, and the team can step in on any conversation.',
        ),
      },
      {
        q: c('كم وقتًا يجب أن يستغرق الرد على العميل؟', 'How long should a reply take?'),
        a: c(
          'لا يوجد رقم يصلح لكل متجر. اختر هدفًا يناسب منتجك وساعات عملك، واكتبه حيث يراه الفريق، ثم قِس عدد المحادثات التي تجاوزته لا المتوسط. الحالات المتأخرة القليلة هي التي تضيّع عملاء، والمتوسط يخفيها.',
          'There is no number that fits every store. Pick a goal that suits your product and working hours, write it where the team sees it, then measure how many conversations exceeded it rather than the average. The few late cases are what lose customers, and an average hides them.',
        ),
      },
      {
        q: c('ما أسرع تحسين يمكن تطبيقه اليوم؟', 'What is the fastest improvement I can apply today?'),
        a: c(
          'قائمة واحدة تُسمّى "ينتظر ردنا"، تُراجع مرتين في اليوم في وقتين ثابتين. هذه القائمة وحدها تمنع أن تُدفن رسالة تحت رسائل أحدث، وهي أرخص خطوة وأكثرها أثرًا، ولا تحتاج أي أداة.',
          'One list called "waiting for us", reviewed twice a day at two fixed times. That list alone prevents a message from being buried under newer ones, and it is the cheapest step with the largest effect, needing no tool at all.',
        ),
      },
      {
        q: c('كيف أمنع تكرار الرد على العميل نفسه من شخصين؟', 'How do I stop two people replying to the same customer?'),
        a: c(
          'اجعل لكل محادثة مسؤولًا واحدًا مكتوبًا بالاسم، واتفق أن صاحب الاسم هو من يرد حتى يُسلّم المحادثة بملاحظة واضحة. هذا يحل المشكلة أكثر من أي تنبيه، لأن التنبيه قد يُقرأ ويُنسى، أما الاسم فيمنع الالتباس من الأصل.',
          'Give every conversation one owner written by name, and agree that the named person replies until the conversation is handed over with a clear note. This solves the problem better than any alert, because an alert can be read and forgotten, while a name prevents the confusion at the source.',
        ),
      },
      {
        q: c('هل الردود الجاهزة تجعل المتجر يبدو غير شخصي؟', 'Do ready replies make a store feel impersonal?'),
        a: c(
          'قد يحدث ذلك إن أُرسلت كما هي في كل مرة. الحل أن يبدأ الرد بجملة واحدة مرتبطة بما قاله العميل فعلًا، ثم يأتي القالب بعدها للمعلومة الدقيقة. هذا يوفر الوقت ويُشعر العميل أنه قُرئ، لا أنه صُودف.',
          'It can happen if they are sent as-is every time. The fix is to open the reply with one sentence tied to what the customer actually said, then use the template for the precise information. That saves time and makes the customer feel read, not processed.',
        ),
      },
    ],
    related: ['how-to-sell-on-whatsapp-organized', 'ai-assistant-for-store-customer-replies'],
    solution: 'unified-inbox',
  },
};
