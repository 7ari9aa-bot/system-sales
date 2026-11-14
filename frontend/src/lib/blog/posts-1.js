// Blog articles, part 1 (expanded). Same rules as solutions-content.js:
//   * Practical, step-by-step advice a store owner can use without FIHRIST.
//   * FIHRIST appears only as a tool, only with capabilities it really has.
//   * No invented statistics, studies, customers, prices or guarantees.
// Body blocks: { h: heading } | { p: paragraph } | { ul: [items] } | { ol: [items] }

const c = (ar, en) => ({ ar, en });

export const POSTS_1 = {
  'how-to-sell-on-whatsapp-organized': {
    date: '2026-11-15',
    minutes: 9,
    title: c('كيف تبيع على واتساب بشكل منظم | FIHRIST', 'How to Sell on WhatsApp in an Organized Way | FIHRIST'),
    description: c(
      'دليل عملي لتنظيم البيع على واتساب: قالب لاستلام الطلب، ردود جاهزة، مسؤول وحالة لكل محادثة، ومتابعة بموعد.',
      'A practical guide to organizing WhatsApp sales: an order template, ready replies, an owner and status per chat, and dated follow-ups.',
    ),
    h1: c('كيف تبيع على واتساب بشكل منظم', 'How to sell on WhatsApp in an organized way'),
    lede: c(
      'واتساب سهّل البيع، لكنه لم يُصمَّم لإدارة المبيعات. عندما تكبر الرسائل يضيع الطلب بين صورة ورسالة صوتية وسؤال عن السعر. هذا الدليل يحوّل العمل إلى خطوات واضحة، ويشرح ما تفعله عندما يتعثر شيء.',
      'WhatsApp made selling easy, but it was not built to manage sales. As messages grow, an order gets lost between a photo, a voice note, and a price question. This guide turns the work into clear steps, and explains what to do when something slips.',
    ),
    body: [
      { h: c('لماذا يضيع البيع على واتساب؟', 'Why sales get lost on WhatsApp') },
      { p: c(
        'المشكلة ليست في التطبيق نفسه، بل في أن كل شيء يعيش في خيط واحد طويل. السؤال، والصورة، والرسالة الصوتية، والاتفاق، والعنوان، وتعديل المقاس، كلها رسائل متتالية في نفس المكان. بعد يومين لا أحد يتذكر ما اتُّفق عليه بالضبط، ولا من ردّ على من، ولا إن كان المبلغ شمل التوصيل أم لا.',
        'The problem is not the app itself. Everything lives in one long thread: the question, the photo, the voice note, the agreement, the address, the size change, all consecutive messages in the same place. Two days later nobody remembers exactly what was agreed, who replied to whom, or whether the amount included delivery.',
      ) },
      { p: c(
        'تظهر أربعة أعراض عادة. الأول: عميل سأل ولم يتلقَّ ردًا لأن رسالته غرقت بين رسائل أخرى. الثاني: طلب اتُّفق عليه ولم يُسجَّل، ثم نُسي. الثالث: عميل قديم لم يتواصل معه أحد منذ شهور رغم أنه كان راضيًا. الرابع: طلبان متشابهان اختلطت تفاصيلهما، فوصل منتج بمقاس خطأ. كل خطوة في هذا الدليل تعالج واحدًا من هذه الأعراض أو أكثر.',
        'Four symptoms usually show up. First: a customer asked and never got a reply, because the message sank under others. Second: an order was agreed and never recorded, then forgotten. Third: an old customer nobody contacted for months, even though they were happy. Fourth: two similar orders whose details got mixed, so a wrong size shipped. Each step below treats one or more of these.',
      ) },
      { h: c('خمسة قرارات قبل أن ترسل رسالة واحدة', 'Five decisions before you send a single message') },
      { p: c(
        'قبل التنظيم تحتاج أن تحسم خمسة أمور. معظم الفوضى لا تأتي من كثرة العمل، بل من قرارات مؤجلة يعيد الفريق مناقشتها كل يوم.',
        'Before organizing, settle five things. Most chaos comes not from too much work but from postponed decisions the team reopens every day.',
      ) },
      { ol: [
        c('أين يُكتب الطلب: مكان واحد فقط، وليس مكانين.', 'Where the order is written: one place only, not two.'),
        c('من يرد على ماذا: من يملك أسئلة السعر، ومن يملك الشكاوى، ومن يملك التوصيل.', 'Who answers what: who owns price questions, who owns complaints, who owns delivery.'),
        c('متى ترد: هل تقبل أن تنتظر رسالة نصف يوم في ساعات العمل؟ اكتب الحد بوضوح.', 'When you reply: will you let a message wait half a day during working hours? Write the limit down.'),
        c('كيف يُدفع: الطرق المقبولة، وماذا تكتب عند التأكيد.', 'How payment works: the accepted methods, and what you write at confirmation.'),
        c('سياسة الاستبدال: جملة واحدة يفهمها العميل، وتُرسل قبل إغلاق الطلب لا بعده.', 'The exchange policy: one sentence the customer understands, sent before closing the order, not after.'),
      ] },
      { h: c('الخطوة 1: المحادثة للحوار، والسجل للقرار', 'Step 1: the chat is for talking, the record is for deciding') },
      { p: c(
        'القاعدة الأهم في التنظيم كله: الطلب لا يعيش في المحادثة. المحادثة مكان للحوار والصور والأسئلة، والسجل مكان للقرار. عندما تختلط الوظيفتان تصبح المحادثة أرشيفًا لا يمكن البحث فيه.',
        'The most important rule of the whole system: the order does not live in the chat. The chat is for conversation, photos, and questions. The record is for decisions. When the two roles mix, the chat becomes an archive you cannot search.',
      ) },
      { p: c(
        'اختر مكانًا واحدًا فقط، دفترًا أو جدولًا أو نظامًا، واكتب فيه كل طلب بنفس الحقول دائمًا: اسم العميل ورقم يمكن الوصول إليه، والمنتج مع مقاسه أو لونه أو خياره، والكمية، والمبلغ المتفق عليه شاملًا التوصيل أو لا، وطريقة الدفع، والعنوان وطريقة التسليم، وتاريخ الاتفاق وموعد التسليم المتوقع، وحالة الطلب.',
        'Pick one place only, a notebook, a sheet, or a system, and write every order with the same fields every time: customer name and a reachable number, the product with its size, color, or option, quantity, the agreed amount including delivery or not, payment method, address and delivery method, the agreement date and expected delivery date, and order status.',
      ) },
      { p: c(
        'لماذا نفس الحقول في كل مرة؟ لأن المقارنة تحتاج تشابهًا. إن كتبت العنوان مرة في خانة الملاحظات ومرة في خانة منفصلة، فلن تستطيع تصفية الطلبات التي لم تُشحن بعد. الحقول الثابتة هي ما يجعل السجل أداة عمل لا مجرد أرشيف.',
        'Why the same fields every time? Because comparison needs sameness. If you put the address in the notes once and in its own column the next time, you cannot filter the orders that have not shipped yet. Fixed fields are what turn a log into a working tool instead of an archive.',
      ) },
      { h: c('الخطوة 2: قالب واحد لاستلام الطلب', 'Step 2: one template for taking an order') },
      { p: c(
        'أسهل طريقة لمنع الأخطاء أن تُعيد الطلب على العميل في رسالة واحدة قبل تنفيذه. القالب التالي يكفي، بدّل التفاصيل فقط:',
        'The easiest way to prevent mistakes is to read the order back to the customer in one message before you act on it. This template is enough, change only the details:',
      ) },
      { p: c(
        '"أؤكد الطلب: قميص كتان أبيض، مقاس M، عدد ٢، بالمبلغ المتفق عليه شاملًا التوصيل، الدفع عند الاستلام، العنوان: ...، التسليم المتوقع يوم الثلاثاء. هل المعلومات صحيحة؟"',
        '"Confirmed order: white linen shirt, size M, quantity 2, at the agreed amount including delivery, cash on delivery, address: ..., expected delivery Tuesday. Is this correct?"',
      ) },
      { p: c(
        'العميل يقرأ ما فهمته أنت، فيصحح قبل الشحن لا بعده. ثم انسخ الرسالة نفسها إلى سجلك. الرسالة المحفوظة في التطبيق تحفظ الكلام، لكنها لا تجمع الطلب في صف يمكن الرجوع إليه بعد أسبوعين.',
        'The customer reads what you understood, and corrects before shipping rather than after. Then copy the same message into your log. A message saved in the app keeps the words, but it does not gather the order into a row you can return to two weeks later.',
      ) },
      { h: c('الخطوة 3: خمسة ردود جاهزة تكفي معظم المحادثات', 'Step 3: five ready replies cover most chats') },
      { p: c(
        'اجمع الأسئلة التي تسمعها كل يوم واكتب لكل منها ردًا قصيرًا بصوتك، لا بصوت شركة. الهدف ليس الرد الآلي، بل ألا تكتب الجملة نفسها خمسين مرة وتُخطئ في واحدة.',
        'Collect the questions you hear every day and write a short reply to each in your own voice, not a corporate voice. The goal is not robotic replies, but not typing the same sentence fifty times and getting one of them wrong.',
      ) },
      { ul: [
        c('السعر: اذكر المبلغ وما يشمله في سطر واحد، ثم اسأل سؤالًا يفتح الخطوة التالية: هل تفضّل الدفع عند الاستلام أم تحويلًا؟', 'Price: state the amount and what it includes in one line, then ask a question that opens the next step: would you prefer cash on delivery or a transfer?'),
        c('التوفر: اذكر الخيارات الموجودة فعلًا، لا كل الخيارات: المقاس M متوفر بالأبيض والكحلي. هل أرسل لك صور اللونين؟', 'Availability: name the options that actually exist, not all options: size M is available in white and navy. Shall I send photos of both?'),
        c('التوصيل: اذكر المدة والمنطقة وطريقة التتبع إن وُجدت، ثم اطلب العنوان كاملًا.', 'Delivery: state the time, the area, and tracking if you have it, then ask for the full address.'),
        c('الاستبدال: جملة واحدة: الاستبدال متاح خلال مدة محددة بشرط بقاء البطاقة على المنتج. لا تشرح السياسة كاملة إلا إذا سأل.', 'Exchanges: one sentence: exchanges are accepted within a set period if the tag is still attached. Do not explain the whole policy unless asked.'),
        c('الاعتذار عن صنف نفد: اعرض بديلًا أو موعد توفر أو استردادًا، واختر واحدًا لا ثلاثة.', 'Apologizing for a sold out item: offer an alternative, a restock date, or a refund, and pick one, not three.'),
      ] },
      { p: c(
        'احفظ هذه الردود في مكان يصل إليه الفريق كله، في تطبيق ملاحظات أو ملف مشترك. عندما ينضم شخص جديد، يبدأ من صياغة جاهزة بدل أن يخترع أسلوبًا جديدًا.',
        'Keep these replies where the whole team can reach them, in a notes app or a shared file. When someone new joins, they start from a ready phrasing instead of inventing a new style.',
      ) },
      { h: c('الخطوة 4: اسم واحد وحالة واحدة لكل محادثة', 'Step 4: one owner and one status per chat') },
      { p: c(
        'إن كان معك أكثر من شخص، فأخطر ما يحدث أن يظن اثنان أن الآخر ردّ، فينتظر العميل ساعات بلا سبب. الحل بسيط: لكل محادثة مسؤول واحد بالاسم، وحالة واحدة مفهومة.',
        'If more than one person is involved, the most dangerous thing is two people each assuming the other replied, while the customer waits for hours for no reason. The fix is simple: every chat has one named owner and one clear status.',
      ) },
      { ul: [
        c('تنتظر ردنا: آخر رسالة من العميل. هذه أول قائمة تفتحها في الصباح.', 'Waiting for us: the last message is from the customer. This is the first list you open in the morning.'),
        c('تنتظر رد العميل: آخر رسالة منك. تحتاج موعد متابعة، وإلا نُسيت.', 'Waiting for the customer: the last message is yours. It needs a follow-up date, or it gets forgotten.'),
        c('مغلقة: تم البيع أو رُفض أو توقف الحوار. تُغلق بسبب مكتوب، لا بالصمت.', 'Closed: sold, declined, or the conversation stopped. It closes with a written reason, not with silence.'),
      ] },
      { p: c(
        'وعندما تسلّم محادثة لزميل، اكتب في المحادثة نفسها: سلّمت المحادثة إلى زميل، والخطوة التالية إرسال الصور. الرسالة القصيرة تحفظ السياق أفضل من أي اجتماع.',
        'When you hand a chat to a colleague, write it in the chat itself: handed this chat to a colleague, the next step is sending the photos. A short message preserves context better than any meeting.',
      ) },
      { h: c('الخطوة 5: موعد المتابعة يُحدَّد عند أول رد', 'Step 5: set the follow-up date at the first reply') },
      { p: c(
        'كثير من المبيعات لا تضيع برفض صريح، بل بصمت. عميل سأل عن السعر ثم اختفى، وأنت افترضت أنه غير مهتم، وهو في الحقيقة انشغل أو ينتظر قرارًا من شخص آخر.',
        'Many sales are not lost to a clear no, but to silence. A customer asked the price then vanished, you assumed they were not interested, and in fact they got busy or are waiting on someone else.',
      ) },
      { p: c(
        'حدّد موعد المتابعة في اللحظة التي يسأل فيها العميل، لا عندما تتذكر. قاعدة عملية: للأصناف سريعة القرار تابع في اليوم التالي. وللأصناف الأغلى أو المقاسات الخاصة أو من ينتظر موافقة شريك، تابع بعد ثلاثة أيام. وإن لم يأتِ رد بعد محاولتين أو ثلاث، أغلق الحالة برسالة مهذبة تترك الباب مفتوحًا.',
        'Set the follow-up date at the moment they ask, not when you remember. A practical rule: for quick decision items, follow up the next day. For more expensive items, unusual sizes, or customers waiting on a partner, follow up in three days. If two or three attempts bring no reply, close the case with a polite message that leaves the door open.',
      ) },
      { h: c('مثال عملي: ثلاثة طلبات في يوم واحد', 'A worked example: three orders in one day') },
      { p: c(
        'مثال: متجر ملابس صغير يستقبل ثلاث محادثات في صباح واحد. المحادثة الأولى: عميلة تسأل عن فستان وتستفسر عن المقاسات ثم تصمت. المحادثة الثانية: عميل يؤكد قميصين بمقاسين مختلفين، ثم يعود بعد ساعة ويطلب تغيير مقاس واحد منهما. المحادثة الثالثة: عميلة تريد استبدال قطعة وصلت بمقاس صغير.',
        'Example: a small clothing store gets three chats in one morning. First: a customer asks about a dress, asks about sizes, then goes quiet. Second: a customer confirms two shirts in different sizes, then comes back an hour later asking to change one of the sizes. Third: a customer wants to exchange an item that arrived too small.',
      ) },
      { p: c(
        'بلا سجل يحدث ما يلي غالبًا: الطلب الثاني يُجهَّز بالمقاس الأول لأن التعديل جاء في رسالة صوتية لم تُسمع، والطلب الثالث يُنسى لأن الاستبدال ليس بيعًا جديدًا فلا أحد سجّله، والعميلة الأولى لا يعود إليها أحد لأن اسمها لا يظهر في أي قائمة. ثلاث فرص ضاعت في يوم واحد، وليس بسبب سوء نية بل بسبب غياب مكان واحد للحقيقة.',
        'Without a log, this usually happens: the second order is prepared in the first size because the change came in a voice note nobody heard, the third order is forgotten because an exchange is not a new sale so nobody recorded it, and the first customer is never contacted again because her name appears on no list. Three chances lost in one day, not from bad intent but from the absence of one place where the truth lives.',
      ) },
      { p: c(
        'مع السجل تصبح الصورة مختلفة: ثلاثة صفوف، ولكل صف حالة. الصف الثاني يحمل ملاحظة: عُدّل المقاس من L إلى M بعد التأكيد، فيُجهَّز الصحيح. الصف الثالث يحمل نوعًا واضحًا هو استبدال، لا بيعًا جديدًا، مع سبب. والصف الأول يحمل تاريخ متابعة هو الغد. الفرق ليس في عدد الرسائل، بل في أن كل معلومة صار لها موضع واحد.',
        'With a log, the picture changes: three rows, each with a status. The second row carries a note: size changed from L to M after confirmation, so the right item is prepared. The third row carries a clear type, exchange, not a new sale, with a reason. The first row carries a follow-up date of tomorrow. The difference is not the number of messages, it is that every fact now has one home.',
      ) },
      { h: c('أخطاء شائعة وكيف تصلحها', 'Common mistakes and how to fix them') },
      { ul: [
        c('تأجيل الكتابة إلى آخر اليوم: اكتب الصف أثناء المحادثة نفسها. الكتابة بعد ساعتين تعتمد على الذاكرة، والذاكرة تختصر التفاصيل وتُحسّنها دون أن تشعر.', 'Postponing the entry to the end of the day: write the row during the chat. Writing two hours later depends on memory, and memory trims and improves the details without you noticing.'),
        c('السعر في مكان والخصم في مكان آخر: اجعل المبلغ المتفق عليه خانة واحدة، واكتب بجانبها ما يشمل وما لا يشمل.', 'The price in one place and the discount in another: make the agreed amount one field, and note beside it what it includes and what it does not.'),
        c('الاعتماد على الرسائل المثبتة: التثبيت يصلح لسياسة واحدة. الباقي يحتاج سجلًا أو ملفًا مشتركًا.', 'Relying on pinned messages: pinning works for one policy. The rest needs a log or a shared file.'),
        c('الرد على كل رسالة فورًا حتى في وقت متأخر: حدّد ساعات رد واضحة، وأرسل خارجها رسالة تقول متى تعود. الصمت المفسَّر أفضل من رد متأخر متعب.', 'Replying to everything instantly, even late at night: set clear reply hours, and outside them send a message saying when you are back. Explained silence beats a late, tired reply.'),
        c('عدم تسجيل سبب الإلغاء: كلمة واحدة، السعر أو المقاس أو التوصيل، تكفي لتعرف ما تصلحه الشهر القادم.', 'Not recording why an order was cancelled: one word, price, size, or delivery, is enough to know what to fix next month.'),
        c('إعادة إرسال الصور من المعرض كل مرة: جهّز ألبومًا لكل منتج، وابعث نفس الصور دائمًا.', 'Sending photos from the gallery from scratch every time: prepare one album per product and always send the same photos.'),
        c('تجاهل من قال سأفكر: هذا أكثر شخص يستحق متابعة، لأنه لم يقل لا.', 'Ignoring the person who said they will think about it: this is the person who most deserves a follow-up, because they did not say no.'),
      ] },
      { h: c('قائمة تحقق: كل يوم وكل أسبوع', 'A checklist: daily and weekly') },
      { p: c(
        'قائمة قصيرة تعمل أفضل من نظام معقد لا يُفتح. خمس دقائق صباحًا وخمس عشرة دقيقة أسبوعيًا تكفي للبداية.',
        'A short list works better than a complex system nobody opens. Five minutes in the morning and fifteen minutes a week is enough to start.',
      ) },
      { ul: [
        c('كل صباح: افتح قائمة تنتظر ردنا وابدأ منها.', 'Every morning: open the waiting for us list and start there.'),
        c('كل طلب جديد: اكتب الصف في السجل قبل أن تغلق المحادثة.', 'Every new order: write the row in the log before you close the chat.'),
        c('كل وعد بموعد: راجع من وعدته اليوم، وأرسل رسالة واحدة صادقة إن تأخرت.', 'Every promised date: review who you promised today, and send one honest message if you are late.'),
        c('كل محادثة انتهت: أغلقها بحالة وسبب، لا تتركها مفتوحة.', 'Every finished chat: close it with a status and a reason, do not leave it open.'),
      ] },
      { ul: [
        c('أسبوعيًا: كم محادثة جديدة وصلت، وكم منها تحوّل إلى طلب؟', 'Weekly: how many new chats arrived, and how many turned into an order?'),
        c('أسبوعيًا: ما السؤال الذي تكرر أكثر؟ انقله إلى وصف المنتج أو إلى رد جاهز.', 'Weekly: which question repeated most? Move it into the product description or a ready reply.'),
        c('أسبوعيًا: من لم يُرد عليه أحد أكثر من يوم؟', 'Weekly: who waited more than a day for a reply?'),
        c('أسبوعيًا: ما سبب الإلغاء الأكثر تكرارًا؟', 'Weekly: what was the most repeated reason for cancellation?'),
      ] },
      { h: c('إذا حدث كذا، فافعل كذا', 'If this happens, do that') },
      { ul: [
        c('إذا تكرر سؤال عن نفس المنتج ثلاث مرات في أسبوع، فالمشكلة في الوصف لا في العميل. أضف المعلومة الناقصة إلى الإعلان أو المنشور.', 'If the same product question comes up three times in a week, the problem is the description, not the customer. Add the missing detail to the post or listing.'),
        c('إذا قال العميل إن المبلغ مرتفع، فلا تخفض فورًا. اسأل: هل المشكلة في المبلغ أم في المقارنة بمنتج آخر؟ ثم اعرض خيارًا أو اشرح الفرق.', 'If the customer says the amount is high, do not discount immediately. Ask: is the issue the amount, or the comparison with another product? Then offer an option or explain the difference.'),
        c('إذا تأخرت البضاعة، أخبر العميل قبل أن يسأل. المبادرة تحفظ الثقة أكثر من الاعتذار المتأخر.', 'If goods are late, tell the customer before they ask. Taking the initiative protects trust better than a late apology.'),
        c('إذا أخطأت في المبلغ، صحّح في نفس المحادثة واذكر الرقم الصحيح، ولا تنتظر أن يكتشف العميل.', 'If you quoted the wrong amount, correct it in the same chat with the right figure, and do not wait for the customer to notice.'),
        c('إذا كنت ترد وحدك على أربعين محادثة يوميًا، فلا تبحث عن تنظيم أفضل فقط، بل حدّد ما يمكن أن ينتظر وما لا يمكن.', 'If you are answering forty chats a day alone, do not only look for better organization, decide what can wait and what cannot.'),
        c('إذا ضاع طلب بالكامل، فاكتب سبب الضياع في السجل. الخطأ الذي لا يُكتب يتكرر.', 'If an order is lost completely, write the cause in the log. A mistake that is not written down repeats.'),
        c('إذا كان العميل يرسل تفاصيله على دفعات، أرسل قالب التأكيد في النهاية بدل جمع التفاصيل من عشر رسائل.', 'If the customer sends details in batches, send the confirmation template at the end instead of assembling the details from ten messages.'),
      ] },
      { h: c('أين تساعدك أداة مثل FIHRIST؟', 'Where a tool like FIHRIST helps') },
      { p: c(
        'كل ما سبق يمكن تنفيذه بدفتر وانضباط، وهذا هو الأهم. الأداة تسرّع العمل ولا تصحح عادة سيئة: إن لم يكن للطلب مكان واحد، فلا نظام سينقذه.',
        'All of the above works with a notebook and discipline, and that is the important part. A tool speeds up the work, it does not fix a bad habit: if the order has no single home, no system will save it.',
      ) },
      { p: c(
        'عندما تكثر المحادثات يصبح الربط اليدوي مرهقًا. يجمع FIHRIST واتساب وماسنجر وإنستغرام والبريد وشات الموقع في صندوق واحد، ويربط المحادثة بالعميل والمنتج والطلب، ويتيح تعيين مسؤول وحالة لكل محادثة، ويوفر تذكيرات وقواعد متابعة يمكن إيقافها. ويمكن ضبط الصلاحيات لكل عضو، ويعمل بالعربية والإنجليزية.',
        'As chats multiply, linking things by hand gets tiring. FIHRIST brings WhatsApp, Messenger, Instagram, email, and web chat into one inbox, links each conversation to the customer, product, and order, lets you assign an owner and a status to each chat, and provides reminders and follow-up rules that can be turned off. Permissions can be set per member, and it works in Arabic and English.',
      ) },
      { p: c(
        'ابدأ بالخطوات أعلاه أولًا. جرّب أسبوعًا بدفتر أو جدول، واعرف أين تتعثر فعلًا، ثم اختر الأداة التي تعالج تلك النقطة.',
        'Start with the steps above first. Try a week with a notebook or a sheet, learn where you actually stumble, then choose the tool that fixes that point.',
      ) },
    ],
    related: ['whatsapp-order-taking-checklist', 'follow-up-customers-who-went-quiet'],
    solution: 'whatsapp-sales-system',
    faq: [
      {
        q: c('هل أحتاج حساب واتساب أعمال لتنظيم البيع؟', 'Do I need a WhatsApp Business account to organize sales?'),
        a: c(
          'لا، التنظيم نفسه يعمل بحساب عادي ودفتر. الحساب التجاري يفيد في أمور مثل الردود الجاهزة وتصنيف المحادثات، أما ربط واتساب بأداة خارجية فيحتاج غالبًا واجهة الأعمال الرسمية. ابدأ بالتنظيم أولًا، ثم قرر إن كنت تحتاج الحساب التجاري.',
          'No, the organization itself works with a normal account and a notebook. The business account helps with things like quick replies and chat labels, while connecting WhatsApp to an outside tool usually needs the official business interface. Start with the organization, then decide whether you need the business account.',
        ),
      },
      {
        q: c('كم رسالة متابعة أرسل قبل أن أتوقف؟', 'How many follow-up messages before I stop?'),
        a: c(
          'مرتان أو ثلاث محاولات بفواصل معقولة تكفي في معظم الحالات، ثم أغلق الحالة برسالة مهذبة. التكرار بلا سبب جديد يضر أكثر مما ينفع. عُد إلى العميل فقط عند وجود شيء فعلي: منتج عاد إلى المخزون، أو معلومة جديدة، أو سؤال يسهّل قراره.',
          'Two or three attempts with sensible gaps is enough in most cases, then close the case with a polite message. Repeating with no new reason does more harm than good. Return to the customer only when there is something real: an item is back in stock, new information, or a question that makes the decision easier.',
        ),
      },
      {
        q: c('هل أرد على العملاء خارج ساعات العمل؟', 'Should I reply to customers outside working hours?'),
        a: c(
          'القرار لك، لكن الأهم أن يكون معلنًا. إن قررت عدم الرد خارج ساعات العمل، فاترك رسالة تقول متى تعود، فهذا أفضل من صمت غير مفسر. بعض المتاجر تختار الرد على الأسئلة السريعة فقط، وتؤجل ما يحتاج تفصيلًا إلى الصباح.',
          'The decision is yours, but it should be announced. If you decide not to reply outside working hours, leave a message saying when you are back, which is better than unexplained silence. Some stores choose to answer only quick questions and postpone anything detailed to the morning.',
        ),
      },
      {
        q: c('كيف أسجل طلبًا وصلت تفاصيله على رسائل كثيرة؟', 'How do I record an order whose details arrived across many messages?'),
        a: c(
          'لا تجمع التفاصيل من عشر رسائل، بل أرسل قالب التأكيد في النهاية واطلب من العميل تصحيح أي خطأ. ثم انسخ القالب نفسه إلى السجل، فيكون الصف والرسالة متطابقين. هذا يقلل الأخطاء ويوفر وقتًا في المراجعة لاحقًا.',
          'Do not assemble the details from ten messages. Send the confirmation template at the end and ask the customer to correct anything wrong. Then copy the same template into the log, so the row and the message match. This cuts mistakes and saves time in later reviews.',
        ),
      },
      {
        q: c('ما أول خطوة إن كان لديّ مئات المحادثات القديمة؟', 'What is the first step if I have hundreds of old chats?'),
        a: c(
          'لا تحاول نقلها كلها، فأنت ستتوقف في منتصف الطريق. ابدأ من اليوم: كل محادثة جديدة تُسجَّل، وكل محادثة قديمة تحتاج متابعة فعلية تُسجَّل وحدها. بعد أسبوعين سيكون لديك سجل حقيقي يخص عملك الحالي، وهذا أنفع من أرشيف ناقص.',
          'Do not try to move all of them, you will stop halfway. Start from today: every new chat gets recorded, and any old chat that really needs follow-up gets recorded on its own. After two weeks you will have a real log of your current work, which is more useful than a partial archive.',
        ),
      },
    ],
  },

  'inventory-tracking-for-small-stores': {
    date: '2026-11-15',
    minutes: 8,
    title: c('كيف تتابع المخزون في متجر صغير | FIHRIST', 'How to Track Inventory in a Small Store | FIHRIST'),
    description: c(
      'طريقة بسيطة لمتابعة المخزون في متجر صغير: تعريف الوحدة، تسجيل الحركة، الحد الأدنى، والجرد، مع مثال عملي وأخطاء شائعة.',
      'A simple way to track inventory in a small store: defining the unit, recording movement, minimum levels, and counting, with a worked example.',
    ),
    h1: c('كيف تتابع المخزون في متجر صغير', 'How to track inventory in a small store'),
    lede: c(
      'لا تحتاج برنامجًا معقدًا لتعرف ما عندك. تحتاج قاعدة واحدة تُطبَّق كل يوم: كل ما يدخل وكل ما يخرج يُسجَّل، والوحدة هي ما تبيعه فعلًا لا ما تسميه. هذا الدليل يشرح القاعدة وتطبيقها على متجر صغير.',
      'You do not need complex software to know what you have. You need one rule applied daily: everything that comes in and goes out gets recorded, and the unit is what you actually sell, not what you call it. This guide explains the rule and how to apply it in a small store.',
    ),
    body: [
      { h: c('لماذا يفشل تتبع المخزون في المتاجر الصغيرة؟', 'Why inventory tracking fails in small stores') },
      { p: c(
        'ثلاثة أسباب تتكرر. الأول: الوحدة غير محددة، فيُسجَّل المنتج ككل بينما يُباع بالمقاس. الثاني: التسجيل متأخر، فيرى صاحب المتجر رقمًا لا يشبه الرف. الثالث: الأرقام موزعة على دفتر وكاشير ومحادثات، فلكل مكان روايته.',
        'Three causes repeat. First: the unit is not defined, so the product is recorded as a whole while it sells by size. Second: recording is late, so the owner sees a number that does not match the shelf. Third: numbers are spread across a notebook, a cashier, and chats, so each place tells its own story.',
      ) },
      { p: c(
        'النتيجة أن الجرد يتحول إلى مفاجأة: تكتشف أن ما حسبته موجودًا غير موجود، وما حسبته راكدًا قد نُفد. والعلاج ليس برنامجًا أغلى، بل تعريف واضح وحركة مسجلة في وقتها.',
        'The result is that counting becomes a surprise: what you thought was there is gone, and what you thought was slow has sold out. The cure is not more expensive software, it is a clear definition and movement recorded on time.',
      ) },
      { h: c('الخطوة 1: عرّف الوحدة قبل أي شيء', 'Step 1: define the unit before anything else') },
      { p: c(
        'قميص أزرق مقاس M يختلف عن قميص أزرق مقاس L، ويختلف عن نفسه باللون الكحلي. إن كتبت قميص أزرق: عشرون قطعة، فأنت تعرف رقمًا ولا تعرف جوابًا. السؤال الذي سيأتيك غدًا هو: هل عندك مقاس L بالأزرق؟ والرقم الكلي لا يجيب.',
        'A blue shirt in size M is not the same as a blue shirt in size L, nor the same as the navy one. If you write blue shirt: twenty pieces, you know a number but not an answer. The question you will get tomorrow is: do you have size L in blue? The total cannot answer it.',
      ) },
      { p: c(
        'الوحدة هي أصغر شيء تبيعه منفصلًا: المنتج مع خياره. في الملابس: القطعة والمقاس واللون. في الأحذية: الموديل والمقاس. في مستحضرات العناية: العبوة بالحجم. اجلس مرة واحدة واكتب وحداتك، ثم استخدم نفس التسمية في كل مكان، في الإعلان وفي المحادثة وفي السجل.',
        'The unit is the smallest thing you sell separately: the product with its option. In clothing: the item, the size, and the color. In shoes: the model and the size. In skin care: the bottle by volume. Sit down once and write your units, then use the same naming everywhere, in the listing, in the chat, and in the record.',
      ) },
      { h: c('الخطوة 2: جدول بخمسة أعمدة يكفي', 'Step 2: five columns are enough') },
      { p: c(
        'لا تحتاج جدولًا فيه عشرون عمودًا. خمسة تكفي لتبدأ: اسم الوحدة، والكمية الحالية، والحد الأدنى، وآخر حركة وتاريخها، وملاحظة قصيرة. العمود الأخير هو الأكثر إهمالًا وهو الأكثر نفعًا، لأنه يحمل سبب التسوية أو اسم المورد أو ملاحظة عن التغليف.',
        'You do not need a sheet with twenty columns. Five are enough to start: the unit name, the current quantity, the minimum level, the last movement and its date, and a short note. The last column is the most neglected and the most useful, because it holds the reason for an adjustment, the supplier name, or a packing note.',
      ) },
      { p: c(
        'إن استخدمت جدولًا إلكترونيًا، فاجعل صفًا واحدًا لكل وحدة، لا لكل منتج. وولّد التسمية بنفس الترتيب دائمًا: القطعة ثم اللون ثم المقاس. الترتيب الثابت يمنع ازدواج الوحدة نفسها بصيغتين، وهو خطأ يستهلك وقتًا في البحث ويُفسد المجاميع.',
        'If you use a spreadsheet, make one row per unit, not per product. Build the name in the same order every time: item, then color, then size. A fixed order prevents the same unit appearing twice in two spellings, a mistake that consumes search time and spoils totals.',
      ) },
      { h: c('الخطوة 3: سجّل ثلاث حركات فقط', 'Step 3: record only three movements') },
      { ul: [
        c('دخول: بضاعة وصلت من المورد. سجّل الكمية الفعلية لا المطلوبة، وإن وصلت ناقصة فاكتب الفرق في اليوم نفسه.', 'In: goods arrived from the supplier. Record the actual quantity, not the ordered one, and if it came short write the difference the same day.'),
        c('خروج: بيع. كل بيع يخصم من وحدته، أي من المقاس واللون المحددين.', 'Out: a sale. Each sale deducts from its own unit, meaning the specific size and color.'),
        c('تسوية: تالف أو مفقود أو مرتجع، مع سبب مكتوب بكلمة أو جملة.', 'Adjustment: damaged, lost, or returned, with the reason written in a word or a sentence.'),
      ] },
      { p: c(
        'كل حركة تحتاج تاريخًا. التاريخ هو ما يسمح لك لاحقًا بسؤال: ماذا حدث في هذا الأسبوع؟ وبدون تاريخ يصبح السجل صورة واحدة، والصور لا تحكي حركة.',
        'Every movement needs a date. The date is what later lets you ask: what happened this week? Without a date the record becomes a single picture, and a picture does not tell movement.',
      ) },
      { h: c('الخطوة 4: اخصم عند الاتفاق لا عند التسليم', 'Step 4: deduct at agreement, not at delivery') },
      { p: c(
        'أكثر سبب للبيع المضاعف هو التسجيل المتأخر. إن خصمت الكمية عند التسليم، فالكمية التي تراها أثناء المحادثة قديمة، وقد تَعِد عميلًا بقطعة باعها زميلك قبل دقيقة.',
        'The most common cause of double selling is late recording. If you deduct at delivery, the quantity you see during a chat is stale, and you may promise a customer an item a colleague sold a minute ago.',
      ) },
      { p: c(
        'الخصم عند التأكيد يعني أن الكمية محجوزة. وإن ألغى العميل، أعدها بتسوية مسجلة بسبب الإلغاء. بهذا تبقى المعادلة واضحة: ما تراه هو ما تستطيع بيعه الآن.',
        'Deducting at confirmation means the quantity is reserved. If the customer cancels, return it with a recorded adjustment and the reason. This keeps the equation clear: what you see is what you can sell now.',
      ) },
      { h: c('الخطوة 5: الحد الأدنى بلا أرقام سحرية', 'Step 5: minimum levels without magic numbers') },
      { p: c(
        'الحد الأدنى هو الكمية التي عندها تعيد الطلب. لا يوجد رقم صالح للجميع، لكن هناك طريقة للوصول إليه: خذ مدة وصول المورد، وزد عليها هامشًا للأيام التي يتأخر فيها عادة، ثم احسب كم تبيع من الوحدة في تلك المدة.',
        'The minimum is the quantity at which you reorder. No single number fits everyone, but there is a way to reach yours: take your supplier lead time, add a margin for the days they usually run late, then work out how many of that unit you sell in that window.',
      ) },
      { p: c(
        'مثال: مورد يصل في عشرة أيام، والوحدة تبيع نحو ثلاث قطع في الأسبوع، فالبيع المتوقع في تلك المدة نحو أربع أو خمس قطع. ضع الحد الأدنى عند خمس أو ست، وعدّله بعد ثلاثة أسابيع حسب الواقع. الرقم الأول تقدير، والرقم بعد شهر تجربة.',
        'Example: a supplier delivers in ten days, and the unit sells about three pieces a week, so expected sales in that window are about four or five pieces. Set the minimum at five or six, then adjust after three weeks against reality. The first number is an estimate, the number after a month is experience.',
      ) },
      { p: c(
        'لا تضع حدًا أدنى لكل شيء في اليوم الأول. ابدأ بالأصناف الأسرع حركة، لأن نفادها يكلّفك بيعًا حقيقيًا، بينما تأخر صنف راكد لا يكلّفك شيئًا.',
        'Do not set a minimum for everything on day one. Start with the fastest movers, because running out of them costs you a real sale, while a delayed slow item costs you nothing.',
      ) },
      { h: c('الخطوة 6: اجرد بالعد لا بالتخمين', 'Step 6: count, do not guess') },
      { ol: [
        c('اختر وقتًا هادئًا، وأوقف البيع أثناء العد إن أمكن.', 'Pick a quiet time and pause selling while counting if you can.'),
        c('عدّ الوحدات بيدك، بالمقاس واللون، لا من الذاكرة ولا من فاتورة المورد.', 'Count the units by hand, by size and color, not from memory and not from the supplier invoice.'),
        c('قارن بالرقم في السجل، وسجّل الفرق كتسوية مع سبب.', 'Compare with the number in the record and log any difference as an adjustment with a reason.'),
        c('إن تكرر الفرق في وحدة بعينها، ابحث عن السبب: خطأ تسجيل، أو تلف غير مسجل، أو شيء آخر يستحق المراجعة.', 'If the difference keeps recurring on one unit, look for the cause: a recording error, unrecorded damage, or something else worth reviewing.'),
      ] },
      { p: c(
        'للمتاجر الصغيرة يكفي جرد جزئي أسبوعي للأصناف الأسرع حركة، وجرد كامل شهري. الجرد الكامل كل يوم مضيعة وقت، والجرد السنوي وحده متأخر جدًا.',
        'For small stores, a weekly partial count of the fastest movers and a full count monthly is enough. A full count every day wastes time, and an annual count alone comes far too late.',
      ) },
      { h: c('مثال عملي: متجر ملابس وثلاثة أحداث', 'A worked example: a clothing store and three events') },
      { p: c(
        'مثال: وحدة واحدة هي قميص كتان أبيض مقاس M، في السجل ست قطع، والحد الأدنى ثلاث. يمر يوم بثلاثة أحداث صغيرة.',
        'Example: one unit, a white linen shirt in size M, has six pieces in the record, and the minimum is three. A single day brings three small events.',
      ) },
      { ol: [
        c('طلب أول: قطعتان من نفس الوحدة. المتبقي أربع.', 'First order: two pieces of that unit. Four remain.'),
        c('طلب ثان: قطعة واحدة. المتبقي ثلاث، أي وصلنا إلى الحد الأدنى، فيُكتب طلب المورد في اليوم نفسه لا عند النفاد.', 'Second order: one piece. Three remain, which is the minimum, so the supplier order is written that same day, not when the shelf is empty.'),
        c('مرتجع من وحدة أخرى، قميص أبيض مقاس L: يعود إلى وحدته هو، لا إلى وحدة M. الخلط هنا شائع ويُفسد الرقمين معًا.', 'A return from another unit, a white shirt in size L: it goes back to its own unit, not to size M. Mixing them here is common and spoils both numbers.'),
      ] },
      { p: c(
        'ثم يأتي الجرد في نهاية الأسبوع، فتجد في الرف قطعتين من M بدل ثلاث. الفرق قطعة واحدة، تلف غير مسجل. تُكتب تسوية بسبب تلف، فيصبح الرقم قطعتين، وهو أقل من الحد الأدنى، فيظهر ما يجب فعله بوضوح: إعادة طلب، أو إيقاف الوعد بهذه الوحدة حتى تصل.',
        'Then the count comes at the end of the week and finds two pieces of M on the shelf instead of three. The difference is one piece, unrecorded damage. An adjustment is written with the reason damage, so the number becomes two, which is below the minimum, and the next action becomes obvious: reorder, or stop promising that unit until it arrives.',
      ) },
      { p: c(
        'لاحظ أن اليوم لم يشهد أي حدث استثنائي. ثلاثة أحداث صغيرة فقط، ومع ذلك تغيّر الرقم من ست إلى اثنتين، وتغيّر القرار معه. هذا هو معنى التتبع: قرار يتغير مع الرقم، لا رقم يُكتب للذكرى.',
        'Notice that nothing exceptional happened that day. Three small events, and the number still moved from six to two, and the decision moved with it. That is what tracking means: a decision that changes with the number, not a number written down for the record.',
      ) },
      { h: c('الخطوة 7: اقرأ الحركة لا الكمية', 'Step 7: read movement, not just quantity') },
      { p: c(
        'الكمية تخبرك بما عندك، والحركة تخبرك بما يجب أن تفعله. وحدة عندها عشرون قطعة قد تكون ممتازة إن كانت تبيع، وكارثة إن كانت لم تتحرك منذ شهرين، لأن المال محبوس فيها.',
        'Quantity tells you what you have, movement tells you what to do. A unit with twenty pieces may be excellent if it sells, and a problem if it has not moved for two months, because money is trapped in it.',
      ) },
      { p: c(
        'قارن البيع بين فترتين لنفس الوحدة، واسأل سؤالين: ما الذي يتحرك بسرعة ويحتاج إعادة طلب؟ وما الذي لم يتحرك ويحتاج قرارًا؟ القرار قد يكون عرضًا، أو تجميعًا مع منتج آخر، أو التوقف عن شرائه في الطلب القادم. القرار الثالث هو الأصعب والأكثر نفعًا.',
        'Compare sales across two periods for the same unit, and ask two questions: what moves fast and needs reordering? What has not moved and needs a decision? The decision may be a promotion, a bundle with another product, or stopping the purchase in the next order. The third is the hardest and the most useful.',
      ) },
      { h: c('أخطاء شائعة وكيف تصلحها', 'Common mistakes and how to fix them') },
      { ul: [
        c('تسجيل المنتج ككل بدل الوحدات: ابدأ الآن بفصل المقاسات التي تبيعها فعلًا، واترك الباقي في صف واحد مؤقتًا.', 'Recording the product as a whole instead of by unit: start now by separating the sizes that actually sell, and leave the rest in one row for the moment.'),
        c('تأجيل الخصم إلى آخر اليوم: اخصم عند التأكيد. وإن لم تستطع، فاكتب الطلب في مسودة وأكمله قبل إغلاق المتجر.', 'Postponing the deduction to the end of the day: deduct at confirmation. If you cannot, write the order in a draft and finish it before closing.'),
        c('المرتجعات بلا سبب: كلمة واحدة، المقاس أو العيب أو تغيير رأي، تكفي.', 'Returns with no reason: one word, size, defect, or changed mind, is enough.'),
        c('نسخ الأرقام يدويًا بين دفتر وكاشير: النسخ اليدوي أكبر مصدر للأخطاء، والحل أن يكون للمخزون رقم واحد يقرأه الجميع.', 'Copying numbers by hand between a notebook and a cashier: manual copying is the biggest source of errors, and the fix is one stock number everyone reads.'),
        c('الاعتماد على فاتورة المورد كسجل: الفاتورة تقول ما طلبت، لا ما استلمت. سجّل ما وصل فعلًا.', 'Treating the supplier invoice as the record: the invoice says what you ordered, not what you received. Record what actually arrived.'),
        c('تسميات مختلفة لنفس الوحدة: قميص أبيض M وقميص كتان أبيض وسط هما صنفان في السجل ووحدة واحدة في الواقع. ثبّت التسمية.', 'Different names for the same unit: white shirt M and white linen shirt medium become two items in the record and one unit in reality. Fix the naming.'),
        c('شراء الأصناف الراكدة لأنها رخيصة: انخفاض السعر لا يبرر التكديس، خصوصًا إن كان رأس المال محدودًا.', 'Buying slow items because they are cheap: a low price does not justify piling stock, especially when capital is limited.'),
      ] },
      { h: c('إذا حدث كذا، فافعل كذا', 'If this happens, do that') },
      { ul: [
        c('إذا كان الجرد لا يطابق السجل في وحدة واحدة دائمًا، فالمشكلة في التسجيل لا في السرقة. راجع من يبيع هذه الوحدة ومتى يكتب.', 'If the count never matches the record on one unit, the problem is recording, not theft. Review who sells that unit and when they write it down.'),
        c('إذا وصلت بضاعة ناقصة، سجّل الفرق كتسوية بسبب نقص من المورد، وطالب بالفرق في نفس اليوم مع صورة الفاتورة.', 'If goods arrive short, log the difference as an adjustment with the reason supplier shortfall, and claim it the same day with a photo of the invoice.'),
        c('إذا نفدت وحدة أسرع من توقعك، فلا تعدّل الرقم فقط، بل ارفع الحد الأدنى لها.', 'If a unit runs out faster than expected, do not only fix the number, raise its minimum level.'),
        c('إذا كانت الوحدات متشابهة جدًا، مثل نفس اللون بأسماء تجارية مختلفة، فاستخدم كودًا قصيرًا لكل وحدة، أو بطاقة عليها رمز QR.', 'If units look very similar, such as the same color under different brand names, use a short code per unit, or a card with a QR code.'),
        c('إذا كان نشاطك خدمة أو خياطة، فالمخزون على المواد لا على القطعة النهائية. عرّف الوحدة بما تستهلكه فعلًا.', 'If your business is a service or tailoring, stock sits on materials, not on the finished piece. Define the unit by what it actually consumes.'),
        c('إذا كان لديك أكثر من مكان للبيع، فالقاعدة نفسها: رقم واحد مشترك، وحركة تُسجَّل مرة واحدة.', 'If you sell from more than one place, the rule is the same: one shared number, and each movement recorded once.'),
        c('إذا لم تعرف من أين تبدأ، فاختر عشرة أصناف فقط. عشرة أصناف مسجلة بدقة أنفع من مئة صنف مسجلة نصف تسجيل.', 'If you do not know where to start, pick ten items only. Ten items recorded accurately are more useful than a hundred recorded halfway.'),
      ] },
      { h: c('أين تساعدك أداة مثل FIHRIST؟', 'Where a tool like FIHRIST helps') },
      { p: c(
        'كل ما سبق يعمل بدفتر وجدول، والمبدأ لا يتغير بالأداة: وحدة واضحة، وحركة مسجلة، ورقم واحد يقرأه الجميع.',
        'All of the above works with a notebook and a sheet, and the principle does not change with the tool: a clear unit, recorded movement, and one number everyone reads.',
      ) },
      { p: c(
        'عندما تكثر الوحدات والطلبات يصبح التحديث اليدوي متعبًا. في FIHRIST تُسجَّل المقاسات والألوان والخيارات كوحدات مخزون منفصلة لكل منها سعر وكمية، وكل طلب يخصم الكمية المباعة، ويمكن تعريف الصنف برمز QR، ومقارنة حركة الأصناف بين فترات. ويمكن ضبط صلاحيات كل عضو في الفريق.',
        'As units and orders multiply, updating by hand gets tiring. In FIHRIST, sizes, colors, and options are recorded as separate stock units, each with its own price and quantity, every order deducts the quantity sold, an item can be identified with a QR code, and item movement can be compared across periods. Permissions can be set for each team member.',
      ) },
      { p: c(
        'تبقى النصيحة نفسها: ابدأ بعشرة أصناف، وشهر واحد من الانضباط، قبل أن تنتقل إلى أداة أو إلى مخزون أكبر.',
        'The advice stays the same: start with ten items and one month of discipline, before you move to a tool or to a bigger stock.',
      ) },
    ],
    related: ['prevent-overselling-and-stockouts', 'sales-report-basics-for-store-owners'],
    solution: 'inventory-management-system',
    faq: [
      {
        q: c('هل أحتاج باركود أو رمز QR لبدء تتبع المخزون؟', 'Do I need a barcode or QR code to start tracking stock?'),
        a: c(
          'لا، يمكنك البدء بأسماء موحدة ورقم مكتوب على البطاقة. الباركود ورمز QR يفيدان عندما تكثر الوحدات أو يتشارك أكثر من شخص في البيع، لأنهما يقللان خطأ اختيار الوحدة. ابدأ بالتسمية الموحدة، وأضف الرمز عندما يصبح البحث اليدوي بطيئًا.',
          'No, you can start with consistent names and a number written on the tag. Barcodes and QR codes help when units multiply or more than one person sells, because they reduce the chance of picking the wrong unit. Start with consistent naming, and add the code when manual searching becomes slow.',
        ),
      },
      {
        q: c('كم مرة أجرد المخزون؟', 'How often should I count stock?'),
        a: c(
          'جرد جزئي أسبوعي للأصناف الأسرع حركة، وجرد كامل شهري، يناسب معظم المتاجر الصغيرة. الجرد الكامل كل يوم مضيعة وقت، والجرد السنوي متأخر جدًا لتصحيح الأخطاء. عدّل التكرار بحسب سرعة حركة الأصناف عندك.',
          'A weekly partial count of the fastest movers and a full monthly count suits most small stores. A full count every day wastes time, and an annual count is far too late to correct errors. Adjust the frequency to how fast your items move.',
        ),
      },
      {
        q: c('كيف أسجل المرتجع في المخزون؟', 'How do I record a return in stock?'),
        a: c(
          'سجّله كتسوية تعيد الكمية إلى وحدتها الأصلية، مع سبب مختصر: مقاس، أو عيب، أو تغيير رأي. لا تُعده إلى وحدة أخرى حتى لو كان المنتج مشابهًا، لأن ذلك يُفسد رقمين معًا. وإن كانت القطعة غير قابلة للبيع، فسجّلها تالفًا ولا تعيدها إلى المتاح.',
          'Log it as an adjustment that returns the quantity to its original unit, with a short reason: size, defect, or changed mind. Do not return it to another unit even if the product is similar, because that spoils two numbers at once. If the piece cannot be sold, record it as damaged and do not put it back into available stock.',
        ),
      },
      {
        q: c('أيهما أفضل، دفتر أم جدول إلكتروني؟', 'Which is better, a notebook or a spreadsheet?'),
        a: c(
          'الدفتر أسرع في البداية ولا يحتاج شحنًا أو تدريبًا، لكن الجدول الإلكتروني يسهّل الجمع والمقارنة بين الفترات والبحث عن وحدة. الأهم من الوسيلة أن يكون هناك مكان واحد يكتب فيه الجميع، وأن تُسجَّل الحركة في وقتها. كثير من المتاجر تبدأ بدفتر ثم تنتقل إلى جدول عندما يكبر العدد.',
          'A notebook is faster at the start and needs no charging or training, but a spreadsheet makes totals, period comparisons, and searching for a unit easier. What matters more than the medium is that there is one place everyone writes in, and that movement is recorded on time. Many stores start with a notebook and move to a sheet as the count grows.',
        ),
      },
      {
        q: c('كيف أعرف الأصناف التي لا تتحرك؟', 'How do I find the items that do not move?'),
        a: c(
          'لكل وحدة، سجّل تاريخ آخر بيع. أي وحدة مرّ عليها شهر بلا حركة فهي مرشحة لقرار: عرض، أو دمج مع منتج آخر، أو التوقف عن شرائها. لا تعتمد على الإحساس، فالأصناف الراكدة تختفي على الرف وتُنسى.',
          'For each unit, record the date of the last sale. Any unit with a month of no movement is a candidate for a decision: a promotion, a bundle with another product, or stopping the purchase. Do not rely on instinct, slow items hide on the shelf and get forgotten.',
        ),
      },
    ],
  },
};
