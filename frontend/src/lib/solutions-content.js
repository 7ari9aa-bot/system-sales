// Copy for the keyword landing pages under /solutions/* (Arabic) and
// /en/solutions/* (English).
//
// Rules for editing this file:
//   * Only describe capabilities FIHRIST really has (see the public product
//     pages). No invented numbers, customers, awards or guarantees.
//   * Titles stay 30-60 characters, descriptions 50-160 (the prerender script
//     asserts this for every locale).
//   * Every page needs 3+ points, 4+ FAQ entries and distinct wording, so the
//     pages are genuinely different documents and not templated near-duplicates.

const c = (ar, en) => ({ ar, en });

export const SOLUTIONS_INDEX = {
  title: c('حلول FIHRIST لإدارة المبيعات والمحادثات', 'FIHRIST Solutions for Sales and Conversations'),
  description: c(
    'استعرض حلول FIHRIST: نظام مبيعات واتساب، إدارة مخزون، مساعد مبيعات بالذكاء الاصطناعي، صندوق محادثات موحد، وكاشير.',
    'Explore FIHRIST solutions: WhatsApp sales system, inventory management, AI sales assistant, unified inbox, and POS cashier.',
  ),
  h1: c('حلول لكل خطوة في دورة البيع.', 'Solutions for every step of the sales cycle.'),
  lede: c(
    'اختر الجزء الذي يهمك الآن: المحادثات، المخزون، الكاشير، أو المساعد الذكي. كلها تعمل على نفس بيانات العميل والطلب.',
    'Start with the part that matters to you now: conversations, inventory, the cashier, or the AI assistant. All of them share the same customer and order data.',
  ),
};

export const SOLUTIONS = {
  'whatsapp-sales-system': {
    title: c('نظام مبيعات واتساب للمتاجر | FIHRIST', 'WhatsApp Sales System for Stores | FIHRIST'),
    description: c(
      'حوّل محادثات واتساب إلى مبيعات منظمة: اربط كل رسالة بالعميل والمنتج والطلب، وتابع الخطوة التالية من مكان واحد.',
      'Turn WhatsApp conversations into organized sales: link every message to the customer, product, and order, and follow the next step in one place.',
    ),
    kicker: c('نظام مبيعات واتساب', 'WhatsApp sales system'),
    h1: c('حوّل محادثات واتساب إلى مبيعات منظمة.', 'Turn WhatsApp chats into organized sales.'),
    lede: c(
      'معظم المتاجر تبيع في واتساب، لكن الطلب يضيع بين الرسائل. يربط FIHRIST كل محادثة بالعميل والمنتج والطلب، فيعرف فريقك ماذا طُلب وماذا بقي.',
      'Most stores sell on WhatsApp, but orders get lost between messages. FIHRIST links each chat to the customer, product, and order, so your team knows what was asked and what is left.',
    ),
    points: [
      { title: c('الرسالة مرتبطة بالطلب', 'Every message tied to an order'), body: c('سجّل الطلب من داخل المحادثة نفسها، وارجع إليه لاحقًا بدل البحث في الرسائل القديمة.', 'Record the order from inside the conversation and come back to it later instead of scrolling through old messages.') },
      { title: c('سجل عميل واحد', 'One customer record'), body: c('يظهر للفريق من هو العميل وما طلبه سابقًا قبل الرد عليه.', 'Your team sees who the customer is and what they ordered before replying.') },
      { title: c('مسؤول وخطوة تالية', 'An owner and a next step'), body: c('حدّد من يتابع المحادثة، وضع تذكيرًا حتى لا يبرد العميل.', 'Assign who follows the conversation and set a reminder so the customer does not go cold.') },
      { title: c('أسئلة المنتج والسعر', 'Product and price questions'), body: c('اعرض السعر والتوفر والاختيارات المسجلة للمنتج أثناء الرد على العميل.', 'Show the recorded price, availability, and options while you answer the customer.') },
    ],
    faq: [
      { q: c('هل يعمل FIHRIST مع واتساب؟', 'Does FIHRIST work with WhatsApp?'), a: c('نعم. واتساب من القنوات المدعومة، مع ماسنجر وإنستغرام والبريد وشات الموقع.', 'Yes. WhatsApp is a supported channel, alongside Messenger, Instagram, email, and web chat.') },
      { q: c('هل أحتاج إلى حساب واتساب للأعمال؟', 'Do I need a WhatsApp Business account?'), a: c('الربط يتم عبر واجهة واتساب الرسمية للأعمال، ويتطلب إعدادًا من جهة واتساب. تواصل معنا لمعرفة الخطوات المناسبة لمتجرك.', 'The connection uses the official WhatsApp Business interface, which requires setup on the WhatsApp side. Contact us for the steps that fit your store.') },
      { q: c('هل يرد الذكاء الاصطناعي على العملاء؟', 'Does AI reply to customers?'), a: c('عند تفعيل مساعد العملاء، يجيب عن الأسئلة اعتمادًا على بيانات المتجر، ويستطيع فريقك التدخل في أي وقت.', 'When the customer assistant is enabled, it answers questions using store data, and your team can step in at any time.') },
      { q: c('هل يمكن لأكثر من موظف متابعة المحادثات؟', 'Can several team members handle chats?'), a: c('نعم. يمكن إسناد كل محادثة إلى عضو في الفريق ومتابعة حالتها.', 'Yes. Each conversation can be assigned to a team member and tracked.') },
    ],
  },

  'inventory-management-system': {
    title: c('نظام إدارة مخزون مربوط بالمبيعات | FIHRIST', 'Inventory Management Linked to Sales | FIHRIST'),
    description: c(
      'اعرف ما بيع وما بقي: يربط FIHRIST المخزون بالطلبات والمبيعات، ويعرّف الصنف برمز QR لتسجيل البيع بدقة.',
      'See what sold and what is left: FIHRIST links inventory to orders and sales, and identifies items with a QR code for accurate sale records.',
    ),
    kicker: c('إدارة المخزون', 'Inventory management'),
    h1: c('اعرف ما بيع وما بقي في المخزون.', 'Know what sold and what is left in stock.'),
    lede: c(
      'عندما ينفصل المخزون عن المبيعات، يصبح الجرد تخمينًا. في FIHRIST تُسجَّل الكمية المباعة من كل اختيار، فتتحدث الكميات المتبقية مع كل بيع.',
      'When stock is separate from sales, counting becomes guesswork. In FIHRIST the quantity sold from each option is recorded, so remaining stock updates with every sale.',
    ),
    points: [
      { title: c('اختيارات المنتج', 'Product options'), body: c('سجّل المقاسات والألوان والاختيارات كوحدات مخزون مستقلة بسعر وكمية لكل منها.', 'Record sizes, colors, and options as separate stock units, each with its own price and quantity.') },
      { title: c('رمز QR للصنف', 'QR code per item'), body: c('يعرّف رمز QR الصنف ويربطه بتسجيل البيع وحركة المخزون، مع صلاحيات للفريق.', 'A QR code identifies the item and ties it to sale recording and stock movement, with team permissions.') },
      { title: c('من الطلب إلى الكمية', 'From order to quantity'), body: c('كل طلب يخصم الكمية المباعة، فترى ما بقي دون جرد يدوي متكرر.', 'Each order deducts the quantity sold, so you see what is left without repeated manual counts.') },
      { title: c('حركة المنتجات', 'Product movement'), body: c('قارن حركة الأصناف بين الفترات لتعرف ما يتحرك وما يتوقف.', 'Compare item movement across periods to see what sells and what stalls.') },
    ],
    faq: [
      { q: c('هل يربط FIHRIST المخزون بالطلبات؟', 'Does FIHRIST link inventory to orders?'), a: c('نعم. تُسجَّل الكمية المباعة مع الطلب، ويظهر ما بقي في المخزون.', 'Yes. The quantity sold is recorded with the order and the remaining stock is shown.') },
      { q: c('هل يدعم الباركود أو QR؟', 'Does it support barcodes or QR codes?'), a: c('يدعم رمز QR لتعريف الصنف وتسجيل البيع. تواصل معنا لمعرفة أنواع الرموز المدعومة في حالتك.', 'It supports QR codes to identify items and record sales. Contact us for the code types supported in your case.') },
      { q: c('هل يمكن تحديد صلاحيات للفريق؟', 'Can I set team permissions?'), a: c('نعم. يمكن ضبط ما يستطيع كل عضو رؤيته أو تنفيذه.', 'Yes. You can set what each member can see or do.') },
      { q: c('هل أحتاج إلى برنامج منفصل للمخزون؟', 'Do I need separate inventory software?'), a: c('لا. المنتجات والطلبات والمخزون في نفس المنصة، فلا داعي لنقل البيانات بينها.', 'No. Products, orders, and stock live on the same platform, so there is no data to move between tools.') },
    ],
  },

  'ai-sales-assistant': {
    title: c('مساعد مبيعات بالذكاء الاصطناعي | FIHRIST', 'AI Sales Assistant for Stores | FIHRIST'),
    description: c(
      'مساعد عملاء يجيب اعتمادًا على بيانات متجرك، ومساعد تحليل يشرح أداء المبيعات. فريقك يراجع ويتدخل وقتما أراد.',
      'A customer assistant that answers from your store data and an analysis assistant that explains sales performance. Your team can review and step in anytime.',
    ),
    kicker: c('مساعد AI', 'AI assistant'),
    h1: c('مساعد ذكي يعتمد على بيانات متجرك.', 'An assistant that works from your store data.'),
    lede: c(
      'يعمل المساعدان على بيانات المتجر المسجلة، لا على التخمين. أحدهما يجيب العملاء عند تفعيله، والآخر يساعدك على قراءة الأداء.',
      'Both assistants work from the data recorded in your store, not guesses. One answers customers when enabled, the other helps you read performance.',
    ),
    points: [
      { title: c('مساعد العملاء', 'Customer assistant'), body: c('يجيب عن أسئلة السعر والتوفر والاختيارات اعتمادًا على المنتجات المسجلة.', 'Answers price, availability, and option questions from the products you recorded.') },
      { title: c('مساعد تحليل المبيعات', 'Sales-analysis assistant'), body: c('يقارن الفترات وحركة المنتجات ونتائج القنوات، ويشرح ما تدعمه البيانات فقط.', 'Compares periods, product movement, and channel results, and explains only what the data supports.') },
      { title: c('مراجعة وتدخل', 'Review and step-in'), body: c('يستطيع فريقك متابعة أي محادثة والتدخل عندما تحتاج الحالة إلى قرار.', 'Your team can follow any conversation and step in when a case needs a decision.') },
      { title: c('البيانات مصدر الأرقام', 'Data is the source of numbers'), body: c('لا يجزم المساعد بسبب لا تدعمه البيانات.', 'The assistant does not assert a cause the data does not support.') },
    ],
    faq: [
      { q: c('هل يجيب الذكاء الاصطناعي تلقائيًا؟', 'Does the AI answer automatically?'), a: c('عند تفعيل مساعد العملاء فقط. يمكنك إبقاءه مغلقًا والاكتفاء بالمتابعة اليدوية.', 'Only when the customer assistant is enabled. You can keep it off and follow up manually.') },
      { q: c('على ماذا يعتمد في إجاباته؟', 'What does it base its answers on?'), a: c('على بيانات المتجر المسجلة في FIHRIST مثل المنتجات والأسعار والتوفر.', 'On the store data recorded in FIHRIST, such as products, prices, and availability.') },
      { q: c('هل يمكن أن يخطئ؟', 'Can it be wrong?'), a: c('أي نظام ذكاء اصطناعي قد يخطئ، ولذلك يراجع فريقك المحادثات ويتدخل عند الحاجة.', 'Any AI system can make mistakes, which is why your team reviews conversations and steps in when needed.') },
      { q: c('هل يدعم العربية؟', 'Does it support Arabic?'), a: c('نعم. الموقع والمنصة تعملان بالعربية والإنجليزية.', 'Yes. The site and platform work in Arabic and English.') },
    ],
  },

  'unified-inbox': {
    title: c('صندوق محادثات موحد للعملاء | FIHRIST', 'Unified Customer Inbox for Stores | FIHRIST'),
    description: c(
      'اجمع واتساب وماسنجر وإنستغرام والبريد وشات الموقع في صندوق واحد مع سجل العميل، ومسؤول واضح لكل محادثة.',
      'Bring WhatsApp, Messenger, Instagram, email, and web chat into one inbox with the customer record and a clear owner for each conversation.',
    ),
    kicker: c('صندوق موحد', 'Unified inbox'),
    h1: c('كل قنوات العملاء في صندوق واحد.', 'All customer channels in one inbox.'),
    lede: c(
      'التنقل بين التطبيقات يبطئ الرد ويضيع السياق. يجمع FIHRIST القنوات الخمس في مكان واحد، ويعرض مع كل رسالة من هو العميل وماذا طلب.',
      'Switching between apps slows replies and loses context. FIHRIST brings the five channels into one place and shows who the customer is and what they asked with every message.',
    ),
    points: [
      { title: c('خمس قنوات', 'Five channels'), body: c('واتساب وماسنجر وإنستغرام والبريد وشات الموقع في قائمة واحدة.', 'WhatsApp, Messenger, Instagram, email, and web chat in a single list.') },
      { title: c('سياق بجانب الرسالة', 'Context beside the message'), body: c('سجل العميل والمنتجات والطلبات ذات الصلة أمام الموظف قبل أن يرد.', 'The customer record and related products and orders are in front of the agent before replying.') },
      { title: c('ملكية وحالة', 'Ownership and status'), body: c('لكل محادثة مسؤول وحالة، فلا تُترك محادثة بلا متابعة.', 'Each conversation has an owner and a status, so none is left without follow-up.') },
      { title: c('تذكيرات المتابعة', 'Follow-up reminders'), body: c('ضع تذكيرًا أو قاعدة متابعة حتى لا تفوتك فرصة بيع.', 'Set a reminder or follow-up rule so you do not miss a sale.') },
    ],
    faq: [
      { q: c('ما القنوات المدعومة؟', 'Which channels are supported?'), a: c('واتساب وماسنجر وإنستغرام والبريد الإلكتروني وشات الموقع.', 'WhatsApp, Messenger, Instagram, email, and web chat.') },
      { q: c('هل يرى الفريق كله كل المحادثات؟', 'Does the whole team see every chat?'), a: c('يمكن ضبط الصلاحيات لتحديد ما يراه كل عضو.', 'Permissions can be set to control what each member sees.') },
      { q: c('هل يحفظ سجل العميل؟', 'Does it keep the customer record?'), a: c('نعم. تُربط المحادثات بسجل العميل ومنتجاته وطلباته.', 'Yes. Conversations are linked to the customer record, products, and orders.') },
      { q: c('كم يستغرق الإعداد؟', 'How long does setup take?'), a: c('يعتمد على القنوات التي تربطها. تواصل معنا لخطة إعداد مناسبة لمتجرك.', 'It depends on the channels you connect. Contact us for a setup plan that fits your store.') },
    ],
  },

  'pos-cashier-system': {
    title: c('نظام كاشير POS مربوط بالمخزون | FIHRIST', 'POS Cashier System Linked to Stock | FIHRIST'),
    description: c(
      'كاشير يسجل البيع ويخصم المخزون ويربط الطلب بالعميل. استخدم نفس بيانات المنتجات في المحادثات والمبيعات.',
      'A cashier that records the sale, updates stock, and links the order to the customer. Use the same product data in conversations and sales.',
    ),
    kicker: c('الكاشير', 'POS cashier'),
    h1: c('كاشير يتحدث معه المخزون تلقائيًا.', 'A cashier your stock keeps up with.'),
    lede: c(
      'سجّل البيع في المحل أو من محادثة، وتنتقل الكمية المباعة إلى المخزون ويظهر الطلب في سجل العميل.',
      'Record a sale in store or from a chat, and the quantity sold moves to stock while the order appears on the customer record.',
    ),
    points: [
      { title: c('بيع سريع', 'Fast checkout'), body: c('اختر الصنف والكمية وسجّل البيع بخطوات قليلة.', 'Pick the item and quantity and record the sale in a few steps.') },
      { title: c('مخزون محدّث', 'Stock stays current'), body: c('تُخصم الكمية المباعة من الاختيار المحدد فتعرف ما بقي.', 'The quantity sold is deducted from the specific option so you know what remains.') },
      { title: c('مرتبط بالعميل', 'Linked to the customer'), body: c('يظهر البيع في سجل العميل ويدعم المتابعة اللاحقة.', 'The sale appears on the customer record and supports later follow-up.') },
      { title: c('صلاحيات الفريق', 'Team permissions'), body: c('حدد من يستطيع تسجيل البيع أو تعديله.', 'Decide who can record or edit a sale.') },
    ],
    faq: [
      { q: c('هل الكاشير جزء من المنصة؟', 'Is the cashier part of the platform?'), a: c('نعم. يعمل داخل FIHRIST على نفس المنتجات والمخزون.', 'Yes. It runs inside FIHRIST on the same products and stock.') },
      { q: c('هل يعمل على الجوال؟', 'Does it work on mobile?'), a: c('الواجهة تعمل في المتصفح. تواصل معنا لمعرفة الأجهزة المناسبة لمتجرك.', 'The interface runs in the browser. Contact us to learn which devices suit your store.') },
      { q: c('هل يربط البيع بالمحادثة؟', 'Does it tie the sale to the conversation?'), a: c('نعم. يمكن ربط الطلب بالمحادثة التي بدأ منها.', 'Yes. The order can be linked to the conversation it started from.') },
      { q: c('هل يدعم أكثر من فرع؟', 'Does it support several branches?'), a: c('تواصل معنا لمناقشة احتياجات الفروع المتعددة.', 'Contact us to discuss multi-branch needs.') },
    ],
  },

  'sales-crm-for-stores': {
    title: c('CRM للمتاجر يربط العميل بالطلب | FIHRIST', 'Sales CRM for Stores and Shops | FIHRIST'),
    description: c(
      'سجل عميل واحد يجمع محادثاته وطلباته ومنتجاته وخطوته التالية، بدل جداول متفرقة وملاحظات ضائعة.',
      'One customer record that gathers conversations, orders, products, and the next step, instead of scattered sheets and lost notes.',
    ),
    kicker: c('CRM للمتاجر', 'Sales CRM for stores'),
    h1: c('سجل عميل واحد بدل ملفات متفرقة.', 'One customer record instead of scattered files.'),
    lede: c(
      'عندما تتوزع بيانات العميل بين واتساب وإكسل ودفتر ملاحظات، يضيع السياق. يجمعها FIHRIST في سجل واحد قابل للمراجعة.',
      'When customer data is split across WhatsApp, spreadsheets, and a notebook, context is lost. FIHRIST gathers it into one reviewable record.',
    ),
    points: [
      { title: c('تاريخ العميل', 'Customer history'), body: c('المحادثات والطلبات والمنتجات في صفحة واحدة.', 'Conversations, orders, and products on a single page.') },
      { title: c('مالك وخطوة تالية', 'Owner and next step'), body: c('لكل عميل مسؤول وموعد متابعة واضح.', 'Each customer has an owner and a clear follow-up date.') },
      { title: c('تجميع حسب النشاط', 'Group by activity'), body: c('افهم من اشترى ومن توقف عن التواصل لتقرر من تتابع.', 'See who bought and who went quiet so you can decide whom to follow up.') },
      { title: c('بيانات خاصة بمتجرك', 'Your store data only'), body: c('تُعزل بيانات كل متجر عن غيره.', 'Each store\'s data is isolated from every other store.') },
    ],
    faq: [
      { q: c('ما الفرق بينه وبين جدول إكسل؟', 'How is it different from a spreadsheet?'), a: c('تُربط المحادثة بالعميل والطلب تلقائيًا، فلا تحتاج إلى النسخ واللصق بين الأدوات.', 'Conversations are linked to the customer and order automatically, so there is no copy and paste between tools.') },
      { q: c('هل يمكن استيراد عملائي؟', 'Can I import my customers?'), a: c('تواصل معنا لمعرفة طرق نقل بياناتك الحالية.', 'Contact us to learn how to bring your existing data over.') },
      { q: c('هل بياناتي آمنة؟', 'Is my data safe?'), a: c('راجع صفحة الأمان لمعرفة كيف تُنظَّم الصلاحيات وسجل النشاط.', 'See the security page to learn how permissions and activity records are organized.') },
      { q: c('هل يناسب المتاجر الصغيرة؟', 'Does it suit small stores?'), a: c('نعم. ابدأ بالمحادثات والطلبات ثم وسّع الاستخدام عند الحاجة.', 'Yes. Start with conversations and orders and expand when you need to.') },
    ],
  },

  'order-management-system': {
    title: c('نظام إدارة الطلبات للمتاجر | FIHRIST', 'Order Management System for Stores | FIHRIST'),
    description: c(
      'سجّل الطلب من المحادثة، واربطه بالعميل والمنتج والمخزون، وتابع ما تم وما يحتاج متابعة.',
      'Record the order from the conversation, link it to the customer, product, and stock, and track what is done and what needs follow-up.',
    ),
    kicker: c('إدارة الطلبات', 'Order management'),
    h1: c('من رسالة العميل إلى طلب مسجل.', 'From a customer message to a recorded order.'),
    lede: c(
      'الطلبات التي تُكتب في الرسائل يسهل نسيانها. في FIHRIST يبدأ الطلب من المحادثة ويظل مرتبطًا بها وبالعميل والمخزون.',
      'Orders written in messages are easy to forget. In FIHRIST the order starts in the conversation and stays linked to it, the customer, and stock.',
    ),
    points: [
      { title: c('طلب من المحادثة', 'Order from the chat'), body: c('أنشئ الطلب أثناء الحديث مع العميل دون مغادرة المحادثة.', 'Create the order while talking to the customer, without leaving the conversation.') },
      { title: c('منتج واختيار وكمية', 'Product, option, and quantity'), body: c('سجّل المنتج والاختيار والكمية بدقة لكل طلب.', 'Record the product, option, and quantity precisely for each order.') },
      { title: c('أثر على المخزون', 'Effect on stock'), body: c('تنتقل الكمية المباعة إلى المخزون فتبقى الأرقام متسقة.', 'The quantity sold moves to stock so numbers stay consistent.') },
      { title: c('متابعة بعد الطلب', 'Follow-up after the order'), body: c('ضع تذكيرًا لمتابعة التسليم أو رضا العميل.', 'Set a reminder to follow up on delivery or customer satisfaction.') },
    ],
    faq: [
      { q: c('هل يمكن ربط الطلب بالمحادثة؟', 'Can an order be linked to a conversation?'), a: c('نعم. يبقى الطلب مرتبطًا بالمحادثة وسجل العميل.', 'Yes. The order stays linked to the conversation and the customer record.') },
      { q: c('هل يدعم الدفع الإلكتروني؟', 'Does it support online payment?'), a: c('تواصل معنا لمعرفة خيارات الدفع المتاحة حاليًا.', 'Contact us to learn which payment options are currently available.') },
      { q: c('هل أرى الطلبات حسب القناة؟', 'Can I see orders by channel?'), a: c('تساعد بيانات الطلبات على قراءة نتائج القنوات ومقارنتها.', 'Order data helps you read and compare channel results.') },
      { q: c('هل يمكن تعديل الطلب؟', 'Can an order be edited?'), a: c('يمكن للفريق تحديث الطلب وفق الصلاحيات الممنوحة له.', 'The team can update an order according to the permissions it has.') },
    ],
  },
};

export const SOLUTION_SLUG_LIST = Object.keys(SOLUTIONS);
