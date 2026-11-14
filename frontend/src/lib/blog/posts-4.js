// Blog articles, expanded batch 4. Same house rules as posts-1.js and posts-2.js:
//   * Practical advice a store owner can use without FIHRIST.
//   * FIHRIST appears only in the final section, only with capabilities it really has.
//   * No invented statistics, studies, customers, prices or guarantees.
//   * No em dashes and no en dashes in either language.
// Body blocks: { h: heading } | { p: paragraph } | { ul: [items] } | { ol: [items] }

const c = (ar, en) => ({ ar, en });

export const POSTS_4 = {
  'whatsapp-order-taking-checklist': {
    date: '2026-11-15',
    minutes: 8,
    title: c(`قائمة تحقق لاستلام الطلبات على واتساب | FIHRIST`, `A Checklist for Taking Orders on WhatsApp | FIHRIST`),
    description: c(
      `قائمة تحقق تفصيلية لاستلام الطلب على واتساب: ما تؤكده، وما تسجله، ورسالة تأكيد جاهزة، وحلول التعديل والإلغاء والنفاد.`,
      `A detailed WhatsApp order checklist: what to confirm, what to record, a ready confirmation message, and fixes for changes, cancellations, and stockouts.`,
    ),
    h1: c(`قائمة تحقق لاستلام الطلبات على واتساب`, `A checklist for taking orders on WhatsApp`),
    lede: c(
      `أخطاء الطلبات نادرًا ما تأتي من سوء نية، بل من تفصيلة لم تُؤكَّد: مقاس، لون، عنوان، أو سعر لم يُحسب معه التوصيل. هذه قائمة تمر عليها قبل إغلاق كل طلب، مع أمثلة وقوالب جاهزة.`,
      `Order mistakes rarely come from bad intent. They come from one unconfirmed detail: a size, a color, an address, or a price quoted without delivery. Here is a checklist to run through before closing every order, with worked examples and ready templates.`,
    ),
    body: [
      { h: c(`لماذا تفشل الطلبات على واتساب؟`, `Why orders fail on WhatsApp`) },
      { p: c(
        `الطلب الذي يفشل على واتساب نادرًا ما يفشل لأنه صعب. يفشل لأن تفصيلة واحدة بقيت في ذهن طرف واحد. العميل فهم أن التوصيل مجاني، وأنت فهمت أن المقاس L، والمنتج وصل مختلفًا، والنتيجة مرتجع وخصم من الربح وإحساس سيئ عند الطرفين.`,
        `An order that fails on WhatsApp rarely fails because it is difficult. It fails because one detail stayed in one person's head. The customer understood delivery was free, you understood size L, the wrong item arrived, and the result is a return, a cut into your profit, and a bad feeling on both sides.`,
      ) },
      { p: c(
        `أربعة أنماط تتكرر أكثر من غيرها: رسالة صوتية فُهمت بشكل مختلف، وصورة منتج بدون تحديد المقاس أو اللون، وعنوان كُتب على عجل بدون علامة مميزة، وسعر ذُكر قبل احتساب التوصيل. كل نمط من هذه يعالجه بند واحد في القائمة أدناه.`,
        `Four patterns repeat more than any others: a voice note understood differently, a product photo without stating size or color, an address typed in a hurry with no landmark, and a price quoted before delivery was added. Each of these is cured by one item on the checklist below.`,
      ) },
      { p: c(
        `الحل ليس موهبة خاصة، بل لحظة واحدة اسمها التأكيد: تجمع كل ما اتفقتم عليه في رسالة واحدة، ترسلها للعميل، وتنتظر ردًا واضحًا قبل أن تلمس المخزون أو تعد بشيء.`,
        `The fix is not a special talent. It is one moment called confirmation: you gather everything you agreed on into a single message, send it to the customer, and wait for a clear reply before you touch stock or promise anything.`,
      ) },

      { h: c(`القائمة قبل التأكيد`, `The checklist before you confirm`) },
      { ol: [
        c(`هل الصنف متوفر فعلًا بالمقاس واللون أو الخيار المطلوب، لا بالصنف عمومًا؟`, `Is the item actually in stock in the requested size, color, or option, not just the item in general?`),
        c(`هل قلت السعر النهائي صريحًا، شاملًا التوصيل أو أي رسوم أخرى إن وُجدت؟`, `Did you state the final price explicitly, including delivery or any other charge if it exists?`),
        c(`هل الكمية المطلوبة موجودة، أم أن ما تبقى أقل مما طلبه العميل؟`, `Is the requested quantity available, or is what remains less than the customer asked for?`),
        c(`هل شرحتَ سياسة الاستبدال والإرجاع في جملة واحدة، بلا مبالغة وبلا وعود إضافية؟`, `Did you explain the exchange and return policy in one sentence, with no exaggeration and no extra promises?`),
        c(`هل طريقة الدفع واضحة ومقبولة عندك فعلًا؟`, `Is the payment method clear and actually acceptable to you?`),
        c(`هل موعد التسليم الذي ذكرته قابل للتنفيذ لو تكرر الطلب نفسه من عميل آخر في اليوم ذاته؟`, `Is the delivery time you mentioned doable if another customer places the same order on the same day?`),
        c(`هل تعرف اسم العميل ورقمه، أم أنك تتحدث مع حساب بلا اسم؟`, `Do you know the customer's name and number, or are you talking to an account with no name?`),
      ] },
      { p: c(
        `إن وجدت بندًا واحدًا لا تستطيع الإجابة عنه بـ"نعم"، فتوقف. الطلب في هذه اللحظة مسودة، وليس طلبًا. اسأل العميل أو راجع المخزون ثم أكمل.`,
        `If there is one item you cannot answer with a clear yes, stop. At that moment the order is a draft, not an order. Ask the customer or check the stock, then continue.`,
      ) },

      { h: c(`البيانات التي لا يُغلق الطلب بدونها`, `The details an order cannot close without`) },
      { ul: [
        c(`الاسم الكامل، ورقم هاتف يمكن الرد عليه فعليًا لو لم يرد على واتساب`, `Full name, and a phone number that can actually be answered if WhatsApp goes quiet`),
        c(`العنوان بتفصيل كافٍ: الشارع، رقم المبنى، الدور، وأقرب علامة يعرفها السكان`, `Address with enough detail: street, building number, floor, and a landmark locals know`),
        c(`المقاس واللون أو الخيار، مكتوبًا بالحروف لا بالصورة`, `Size, color, or option written in words, not left as a picture`),
        c(`الكمية رقمًا لا تقديرًا، لأن كلمة "قليل" تعني شيئًا مختلفًا لكل شخص`, `Quantity as a number, not a guess, because "a few" means something different to each person`),
        c(`المبلغ الإجمالي وطريقة الدفع، مع ذكر ما إذا كان الدفع عند الاستلام`, `Total amount and payment method, stating whether it is cash on delivery`),
        c(`اليوم أو الفترة التي يحتمل فيها التسليم، بصيغة يمكن الوفاء بها`, `The day or window when delivery is likely, phrased so you can keep it`),
      ] },
      { p: c(
        `هذه الحقول ليست إجراءً إداريًا، بل هي نفسها ما تحتاجه لاحقًا عندما يسأل العميل "أين طلبي؟". الطلب الذي لا تُسجَّل فيه يصبح ذكرى بعد أسبوع.`,
        `These fields are not paperwork. They are exactly what you need later when a customer asks where their order is. An order that does not record them becomes a memory after a week.`,
      ) },

      { h: c(`رسالة التأكيد: خمسة أجزاء ونموذج جاهز`, `The confirmation message: five parts and a ready template`) },
      { p: c(
        `رسالة التأكيد الجيدة قصيرة لكنها لا تترك مجالًا للتفسير. ترتيبها ثابت في كل مرة: الصنف وخياره، الكمية، المبلغ وطريقة الدفع، التسليم والعنوان، ثم السياسة وسؤال إغلاق واحد.`,
        `A good confirmation message is short but leaves no room for interpretation. Its order is the same every time: the item and its option, the quantity, the amount and payment method, delivery and address, then the policy and one closing question.`,
      ) },
      { ul: [
        c(`الصنف والخيار: يمنع الخطأ الأكثر شيوعًا، وهو الوصول بمقاس أو لون مختلف`, `Item and option: prevents the most common error, arriving with a different size or color`),
        c(`الكمية: يمنع الجدل حول "كنت طلبت قطعتين" و"فهمت قطعة واحدة"`, `Quantity: prevents the argument over "I ordered two" and "I understood one"`),
        c(`المبلغ وطريقة الدفع: يمنع مفاجأة العميل عند التسليم`, `Amount and payment: prevents a surprise at delivery`),
        c(`التسليم والعنوان مكتوبًا: يجعل تصحيح العنوان ممكنًا قبل الشحن لا بعده`, `Delivery and written address: makes correcting the address possible before shipping, not after`),
        c(`السياسة وسؤال الإغلاق: يمنح العميل فرصة الاعتراض قبل أن تتحرك البضاعة`, `Policy and closing question: gives the customer a chance to object before goods move`),
      ] },
      { p: c(
        `النموذج: "تأكيد الطلب: قميص قطني أزرق، مقاس M، عدد 2. الإجمالي [المبلغ] شامل التوصيل، الدفع عند الاستلام. التسليم إلى [الشارع، رقم المبنى، الدور، أقرب علامة]، والفترة المتوقعة [اليوم أو الفترة]. الاستبدال متاح خلال [المدة] بشرط عدم استخدام القطعة. هل كل البيانات صحيحة؟"`,
        `Template: "Order confirmation: blue cotton shirt, size M, quantity 2. Total [amount] including delivery, cash on delivery. Delivery to [street, building, floor, landmark], expected [day or window]. Exchange within [period] provided the item is unused. Are all the details correct?"`,
      ) },
      { p: c(
        `قاعدة الإغلاق: لا تعتبر الطلب مؤكدًا برد مثل "تمام" فقط إن كان فيه أكثر من صنف أو أكثر من تفصيلة. اطلب تأكيدًا صريحًا على الرسالة المجمعة، لأن "تمام" قد تعني "استلمت رسالتك" عند بعض الناس.`,
        `Closing rule: do not treat an order as confirmed by a reply like "okay" alone when it contains more than one item or more than one detail. Ask for an explicit yes to the gathered message, because for some people "okay" means "I received your message".`,
      ) },

      { h: c(`مثال كامل من أول رسالة إلى التسليم`, `A full example, from first message to delivery`) },
      { ol: [
        c(`العميل: السلام عليكم، هل لديكم القميص الأزرق؟`, `Customer: Hello, do you have the blue shirt?`),
        c(`المتجر: وعليكم السلام، متوفر بمقاس M و L. هل تريد أن أذكر لك المقاسات المتاحة بالتفصيل؟`, `Store: Hello, it is available in M and L. Would you like the available sizes in detail?`),
        c(`العميل: مقاس M، وأريد قطعتين.`, `Customer: M, and I want two.`),
        c(`المتجر: مقاس M متوفر، وسعر القطعة هو السعر المعلن، والتوصيل إلى منطقتك [المبلغ]. هل أحجز لك القطعتين؟`, `Store: Size M is available, the price is the listed one per piece, and delivery to your area is [amount]. Shall I reserve the two for you?`),
        c(`العميل: نعم، احجز.`, `Customer: Yes, reserve them.`),
        c(`المتجر: تأكيد الطلب: قميص قطني أزرق، مقاس M، عدد 2. الإجمالي [المبلغ] شامل التوصيل، الدفع عند الاستلام. التسليم إلى [الشارع، رقم المبنى، الدور، أقرب علامة]، والفترة المتوقعة [اليوم أو الفترة]. الاستبدال متاح خلال [المدة] بشرط عدم استخدام القطعة. هل كل البيانات صحيحة؟`, `Store: Order confirmation: blue cotton shirt, size M, quantity 2. Total [amount] including delivery, cash on delivery. Delivery to [street, building, floor, landmark], expected [day or window]. Exchange within [period] provided the item is unused. Are all the details correct?`),
        c(`العميل: صحيح، لكن العنوان بجوار المسجد.`, `Customer: Correct, but the address is by the mosque.`),
        c(`المتجر: تم، سجلت العلامة. الطلب مسجل والمقاس محجوز، وسنرسل لك رسالة قبل الخروج للتسليم.`, `Store: Noted, I added the landmark. The order is recorded and the size is reserved, and we will message you before dispatch.`),
        c(`العميل: شكرًا.`, `Customer: Thanks.`),
        c(`المتجر: شكرًا لك. إن احتجت تعديل مقاس أو عنوان قبل التجهيز، أخبرني وأعدله.`, `Store: Thank you. If you need a size or address change before packing, tell me and I will update it.`),
      ] },
      { p: c(
        `لاحظ ما حدث في المحادثة القصيرة: حُجزت الكمية من المقاس الصحيح، وتأكد العنوان قبل التجهيز، وعرف العميل إلى متى يستطيع التعديل، وكل ذلك في دقائق. لم يُشترَ شيء جديد ولم تُستخدم أداة خاصة، فقط ترتيب ثابت للكلام.`,
        `Notice what happened in that short conversation: the quantity was reserved from the right size, the address was confirmed before packing, and a follow-up point was set after delivery, all in a few minutes. Nothing new was bought and no special tool was used, only a fixed order to the conversation.`,
      ) },

      { h: c(`التعديل والإلغاء: قواعد تحمي الطرفين`, `Changes and cancellations: rules that protect both sides`) },
      { p: c(
        `التعديل ليس مشكلة، المشكلة أن يصل التعديل بعد أن تكون البضاعة خرجت. لذلك أنسب حل هو إعلان حدود زمنية واضحة في رسالة التأكيد نفسها، فيعرف العميل إلى متى يستطيع أن يغيّر رأيه.`,
        `A change is not a problem. The problem is a change that arrives after the goods have left. So the best fix is to state clear time limits in the confirmation message itself, so the customer knows how long they can change their mind.`,
      ) },
      { ul: [
        c(`قبل التجهيز: التعديل أو الإلغاء حق مكفول، غيّر بلا جدال وحدّث السجل`, `Before packing: change or cancellation is a fair right, change without argument and update the record`),
        c(`بعد التجهيز وقبل الشحن: التعديل ممكن إن لم يكن قد خرج من المتجر، وإن خرج فالحل استبدال لا تعديل`, `After packing but before dispatch: a change is possible if it has not left the shop; if it has, the answer is an exchange, not a change`),
        c(`بعد الشحن: لا تعديل على الطلب نفسه، لكن للعميل أن يرفض الاستلام أو يستبدل وفق السياسة`, `After dispatch: no change to the order itself, but the customer may refuse delivery or exchange under the policy`),
        c(`الإلغاء بعد الخروج: سجّل السبب بوضوح، لأن تكرار الأسباب يكشف مشكلة في الوصف أو في السعر أو في التوصيل`, `Cancellation after dispatch: record the reason plainly, because repeated reasons reveal a problem in the description, the price, or the delivery`),
      ] },
      { p: c(
        `قاعدة مهمة في السجل: لا تمحُ الطلب القديم عند التعديل، بل أضف نسخة جديدة واترك القديمة ظاهرة كملغاة أو معدّلة. عند أي خلاف لاحق، السجل المتسلسل يحل النقاش في ثوانٍ، أما السجل الممحو فيفتحه من جديد.`,
        `An important record rule: do not erase the old order when it changes. Add a new version and keep the old one visible as cancelled or edited. In any later dispute, a sequential record settles the discussion in seconds, while an erased one reopens it.`,
      ) },

      { h: c(`حالات خاصة: الدفع عند الاستلام والعنوان الخطأ والنفاد بعد الاتفاق`, `Special cases: cash on delivery, wrong address, and a stockout after agreement`) },
      { p: c(
        `الدفع عند الاستلام: هذا النوع من الطلبات يحمل مخاطرة أعلى، لأن العميل قد يغيّر رأيه عند الباب. خفّف المخاطرة بتأكيد واحد قبل الخروج للتسليم، ورسالة قصيرة تقول المبلغ المتوقع دفعه بالضبط، وتسجيل نتيجة كل محاولة تسليم: سُلِّم، رُفض، لم يُرد. من يرفض الاستلام مرتين متتاليتين لا يُمنع، لكن يُطلب منه تأكيد إضافي في الطلب الثالث.`,
        `Cash on delivery: these orders carry more risk, because the customer may change their mind at the door. Reduce it with one confirmation before dispatch, a short message stating the exact amount due, and a record of each delivery attempt: delivered, refused, no answer. Someone who refuses twice in a row is not banned, but their third order gets an extra confirmation.`,
      ) },
      { p: c(
        `العنوان الخطأ: لا تعتمد على الخريطة وحدها ولا على اسم الحي. اسأل عن علامة ثابتة يعرفها السكان، ورقم بديل، ووقت يكون فيه أحد في العنوان. إن فشل التسليم، سجّل السبب بالنص الذي قاله المندوب: "الرقم غير موجود"، "لم يرد"، "رفض الاستلام". هذه الجملة هي ما يجعلك تصلح الوصف أو تختار شركة توصيل أفضل في المرة القادمة.`,
        `Wrong address: do not rely on the map alone or on the district name. Ask for a fixed landmark locals know, a backup number, and a time when someone is at the address. If delivery fails, record the reason in the courier's own words: number not found, no answer, refused. That sentence is what lets you fix the description or choose a better courier next time.`,
      ) },
      { p: c(
        `النفاد بعد الاتفاق: هذا أصعب موقف، لأن العميل اعتبر الأمر منتهيًا. تصرفه الصحيح ثلاث خطوات: أخبره فورًا بلا تأجيل، واعرض ثلاثة خيارات لا خيارًا واحدًا (بديل قريب، انتظار بموعد محدد، أو استرداد كامل)، ودعه هو يختار. لا تبدّل الصنف من نفسك ولو كان أفضل، ولا تنتظر ليوم التسليم لتشرح. العميل يسامح على النفاد، ولا يسامح على المفاجأة يوم التسليم.`,
        `A stockout after agreement: this is the hardest moment, because the customer considered the matter closed. The right response is three steps: tell them immediately with no delay, offer three options rather than one (a close alternative, waiting with a specific date, or a full refund), and let them choose. Do not substitute the item on your own even if it is better, and do not wait until delivery day to explain. Customers forgive a stockout. They do not forgive a surprise on delivery day.`,
      ) },

      { h: c(`أخطاء شائعة وإصلاحها`, `Common mistakes and their fixes`) },
      { ul: [
        c(`الخطأ: التسجيل في آخر اليوم. الإصلاح: سجّل قبل أن ترد على العميل التالي، لأن الترتيب الذي تتذكره بعد ساعتين ليس هو الترتيب الحقيقي.`, `Mistake: recording at the end of the day. Fix: record before you answer the next customer, because the order you remember two hours later is not the real order.`),
        c(`الخطأ: الاعتماد على الرسائل الصوتية في الطلبات. الإصلاح: حوّل كل طلب إلى نص في رسالة التأكيد، ولو كان العميل يفضل الصوت.`, `Mistake: relying on voice notes for orders. Fix: turn every order into text in the confirmation message, even if the customer prefers voice.`),
        c(`الخطأ: ذكر السعر قبل احتساب التوصيل. الإصلاح: قل الرقم النهائي دائمًا، أو قل صراحة "السعر بدون توصيل".`, `Mistake: quoting the price before delivery. Fix: always give the final figure, or say plainly "price before delivery".`),
        c(`الخطأ: وعد بموعد تسليم طموح لإغلاق البيع. الإصلاح: أعطِ فترة تستطيع الوفاء بها في يوم مزدحم، فالوعد المتأخر أغلى من الصدق المبكر.`, `Mistake: promising an optimistic delivery date to close the sale. Fix: give a window you can keep on a busy day, because a late promise costs more than early honesty.`),
      ] },

      { h: c(`إذا حدث كذا افعل كذا`, `If this happens, do this`) },
      { ul: [
        c(`العميل لم يرد على رسالة التأكيد: أرسل تذكيرًا واحدًا بعد فترة معقولة، وإن لم يرد فاعتبر الطلب غير مؤكد وأعد الكمية للمخزون بعد أن تخبره أنك فعلت.`, `The customer does not reply to the confirmation: send one reminder after a reasonable gap; if there is still no reply, treat the order as unconfirmed and return the quantity to stock after telling them you did.`),
        c(`العميل قال "تمام" فقط: اسأله سؤالًا مغلقًا واحدًا: "أأكد الطلب بالبيانات المكتوبة فوق؟" فلا يبقى مجال لتفسيرين.`, `The customer only said "okay": ask one closed question, "shall I confirm the order with the details above?" so two readings cannot survive.`),
        c(`العميل طلب تغيير المقاس بعد التجهيز: نفّذ إن كانت القطعة لم تخرج، وإن خرجت فاشرح خيار الاستبدال بجملة واحدة بلا اعتذار طويل.`, `The customer changes the size after packing: do it if the item has not left, and if it has, explain the exchange option in one sentence without a long apology.`),
        c(`العميل قال إن السعر مختلف عما رآه: لا تجادل. أرسل له ما هو مكتوب عندك، وقل "أراجع معك"، ثم صحّح الوصف أو السعر بعد المكالمة.`, `The customer says the price is different from what they saw: do not argue. Send what you have on record, say you will check, then correct the description or price after the call.`),
        c(`المندوب قال إن العميل رفض الاستلام: اتصل بالعميل قبل أي قرار، وسجّل ما يقوله، فبين المندوب والعميل روايتان تحتاجان سماعًا.`, `The courier says the customer refused delivery: call the customer before deciding anything and record what they say, because courier and customer tell two stories worth hearing.`),
        c(`العميل اشتكى من قطعة ناقصة أو تالفة: اطلب صورة، واقترح حلًا واحدًا واضحًا (استبدال أو خصم أو استرداد) بدل فتح خيارات كثيرة على نفسك.`, `The customer complains of a missing or damaged item: ask for a photo and propose one clear remedy (exchange, discount, or refund) instead of opening many options for yourself.`),
      ] },

      { h: c(`قوالب جاهزة للنسخ`, `Ready to copy templates`) },
      { ul: [
        c(`تأكيد: "تأكيد الطلب: [الصنف والخيار]، عدد [الكمية]. الإجمالي [المبلغ] شامل التوصيل، الدفع [الطريقة]. التسليم إلى [العنوان الكامل]، الفترة المتوقعة [الفترة]. الاستبدال خلال [المدة] بشرط عدم الاستخدام. هل البيانات صحيحة؟"`, `Confirmation: "Order confirmation: [item and option], quantity [qty]. Total [amount] including delivery, payment [method]. Delivery to [full address], expected [window]. Exchange within [period] if unused. Are the details correct?"`),
        c(`تعديل: "تم تعديل الطلب. النسخة الجديدة: [التفاصيل]. النسخة السابقة أُلغيت. راجعها وقل لي إن كان فيها شيء غير صحيح."`, `Change: "Your order has been updated. New version: [details]. The previous version is cancelled. Please check it and tell me if anything is wrong."`),
        c(`إلغاء: "تم إلغاء الطلب وإرجاع الكمية للمخزون، ولا يوجد أي مبلغ مستحق عليك. إن أردت الطلب لاحقًا فأنا موجود."`, `Cancellation: "The order is cancelled and the quantity is back in stock. Nothing is owed on your side. If you want to order later, I am here."`),
        c(`نفاد بعد الاتفاق: "أخبار غير سارة: [الصنف] نفد بعد حجز طلبك. عندي ثلاثة اختيارات: [بديل]، أو انتظار حتى [موعد]، أو استرداد كامل. أي واحد يناسبك؟"`, `Stockout after agreement: "Unfortunate news: [item] ran out after your order was reserved. You have three options: [alternative], waiting until [date], or a full refund. Which suits you?"`),
        c(`قبل التسليم: "طلبك خرج للتسليم اليوم. المبلغ المطلوب عند الاستلام [المبلغ]. المندوب سيتصل بك على [الرقم]. إن تغيّر العنوان فأخبرني الآن."`, `Before delivery: "Your order is out for delivery today. Amount due on delivery [amount]. The courier will call [number]. If the address changed, tell me now."`),
        c(`بعد التسليم: "أتمنى أن يكون الطلب قد أعجبك. إن كانت هناك أي مشكلة في المقاس أو القطعة، أخبرني ونجد حلًا."`, `After delivery: "I hope you are happy with the order. If there is any issue with the size or the item, tell me and we will find a solution."`),
      ] },

      { h: c(`ثلاثة أرقام تراقبها كل أسبوع`, `Three numbers to watch every week`) },
      { p: c(
        `لا تحتاج تقريرًا معقدًا لتكتشف أن طريقة استلام الطلبات تحتاج ضبطًا. ثلاثة أرقام بسيطة تكفي في البداية، وتُحسب من سجلك أنت لا من تخمينك.`,
        `You do not need a complex report to discover that your order taking needs tuning. Three simple numbers are enough at the start, and you count them from your own record, not from memory.`,
      ) },
      { ol: [
        c(`نسبة الطلبات التي وصلت للعميل كما اتُّفق من أول مرة. كل طلب رجع يعني تفصيلة لم تُؤكَّد.`, `The share of orders that reached the customer right the first time. Every returned order means a detail was never confirmed.`),
        c(`عدد الطلبات التي أُلغيت أو اعتُذر عنها بعد التأكيد، وسبب كل واحدة. تكرار السبب نفسه هو الخبر الحقيقي.`, `The number of orders cancelled or apologized for after confirmation, with each reason. The same reason repeating is the real news.`),
        c(`عدد المحادثات التي انتهت بلا رد منك أو برد متأخر. هذه أسرع مبيعات تُفقد.`, `The number of conversations that ended with no reply from you or a late one. These are the fastest sales to lose.`),
      ] },

      { h: c(`كيف يساعد FIHRIST؟`, `How FIHRIST helps`) },
      { p: c(
        `كل ما سبق ينفّذه دفتر وجدول وقليل من الانضباط، ولا تحتاج أداة لتبدأ. حين تكثر المحادثات يصبح الربط اليدوي مرهقًا. يجمع FIHRIST واتساب وماسنجر وإنستجرام والبريد والدردشة على الموقع في صندوق واحد، وتُربط كل محادثة بالعميل والمنتج والطلب، مع تعيين مسؤول وحالة لكل محادثة، وتذكيرات متابعة يمكن إيقافها. المخزون يُسجَّل بوحدات للمقاسات والألوان والخيارات، ولكل وحدة سعرها وكميتها، ويخصم كل طلب الكمية التي بيعت. يمكن أيضًا طباعة رمز QR لتمييز القطع. الواجهة تعمل من المتصفح، وبالعربية والإنجليزية.`,
        `Everything above runs on a notebook, a sheet, and a little discipline, and you do not need a tool to start. When conversations multiply, linking things by hand gets tiring. FIHRIST brings WhatsApp, Messenger, Instagram, email, and web chat into one inbox; each conversation links to the customer, product, and order; each conversation can have an owner and a status; and follow-up reminders can be switched off. Stock is recorded as units for sizes, colors, and options, each unit with its own price and quantity, and each order deducts the quantity sold. You can also print a QR code to identify items. The interface runs in a browser, in Arabic and English.`,
      ) },
    ],
    faq: [
      {
        q: c(`هل يجب أن أرسل رسالة تأكيد لكل طلب، حتى الطلب الصغير؟`, `Should I send a confirmation message for every order, even a small one?`),
        a: c(
          `نعم، ولسبب عملي: أصغر الطلبات هي التي تُغلق بسرعة في أقل عدد من الكلمات، وهي أيضًا التي يُنسى فيها المقاس أو العنوان. رسالة التأكيد لا تحتاج أن تكون طويلة، سطران يكفيان إن كان الطلب قطعة واحدة. المهم أن تُرسل قبل أن تلمس المخزون، لأنها اللحظة الوحيدة التي لا يزال فيها التصحيح رخيصًا.`,
          `Yes, for a practical reason: the smallest orders are the ones closed fastest in the fewest words, and also the ones where a size or address gets forgotten. The confirmation need not be long, two lines are enough for a single item. What matters is that it goes out before you touch stock, because that is the only moment when correcting it is still cheap.`,
        ),
      },
      {
        q: c(`كيف أتعامل مع عميل يرفض كتابة طلبه ويريد رسائل صوتية فقط؟`, `How do I handle a customer who refuses to type and only sends voice notes?`),
        a: c(
          `اسمعه كاملًا ثم اكتب أنت الملخص بدل أن تطلب منه الكتابة. أرسل رسالة التأكيد وأضف جملة مثل "كتبت طلبك في رسالة لتأكيده". بهذا تحتفظ بما يريده العميل وتحصل على سجل مكتوب يمكن الرجوع إليه. الرسالة الصوتية تفسير، والنص هو ما يُنفَّذ.`,
          `Listen to it fully, then write the summary yourself instead of asking them to type. Send the confirmation and add a line such as "I wrote your order down so we can confirm it". That way the customer keeps what they prefer and you get a written record to return to. A voice note is an interpretation; the text is what gets executed.`,
        ),
      },
      {
        q: c(`ماذا أفعل إن نفد الصنف بعد أن أكدت الطلب للعميل؟`, `What should I do if the item runs out after I confirmed the order?`),
        a: c(
          `أخبره في نفس اليوم إن أمكن، واعرض ثلاثة خيارات: بديل قريب، أو انتظار بموعد محدد، أو استرداد كامل. لا تختر عنه ولا تؤجل الخبر إلى يوم التسليم. إن كان قد دفع مقدمًا، فابدأ بإجراء الاسترداد قبل أن يطلبه، فهذا يحوّل موقفًا سيئًا إلى موقف يُذكر لصالحك.`,
          `Tell them the same day if you can, and offer three options: a close alternative, waiting with a specific date, or a full refund. Do not choose for them and do not postpone the news to delivery day. If they paid in advance, start the refund before they ask, which turns a bad moment into one they remember in your favour.`,
        ),
      },
      {
        q: c(`هل أطلب من العميل صورة تحويل الدفع قبل تجهيز الطلب؟`, `Should I ask for a payment transfer screenshot before packing the order?`),
        a: c(
          `اطلب تأكيدًا، لكن لا تجعل الصورة وحدها هي الدليل الوحيد. الأفضل أن تراجع حسابك أو محفظتك فعليًا، لأن الصور يمكن أن تكون قديمة أو متشابهة. اجعل القاعدة ثابتة ومعلنة: "نبدأ التجهيز بعد ظهور المبلغ". القاعدة الواضحة تمنع الحرج مع العميل الذي نسي أو تأخر.`,
          `Ask for confirmation, but do not let a screenshot be your only proof. Better to check your own account or wallet, since images can be old or look alike. Make the rule fixed and stated: "we start packing once the amount arrives". A clear rule spares you embarrassment with a customer who forgot or was late.`,
        ),
      },
      {
        q: c(`كيف أقلل المرتجعات في الملابس تحديدًا؟`, `How do I reduce returns specifically for clothing?`),
        a: c(
          `أضف إلى رسالة التأكيد معلومة واحدة عن المقاس، مثل القياس بالسنتيمتر أو ملاحظة أن المقاس يميل إلى الصغر. صورة واحدة على جسم حقيقي أفضل من عشر صور مسطحة. وسجّل سبب كل استبدال: المقاس صغير، المقاس كبير، اللون مختلف. بعد عدد من الطلبات يكون عندك جدول مقاسات مبني على ملاحظات عملائك لا على تخمينك.`,
          `Add one sizing fact to the confirmation, such as a measurement in centimetres or a note that the cut runs small. One photo on a real body beats ten flat ones. And record the reason for every exchange: too small, too big, different color. After enough orders you will have a size guide built from your customers' notes rather than your guesses.`,
        ),
      },
    ],
    related: ['how-to-sell-on-whatsapp-organized', 'prevent-overselling-and-stockouts'],
    solution: 'order-management-system',
  },

  'ai-assistant-for-store-customer-replies': {
    date: '2026-11-15',
    minutes: 9,
    title: c(`هل يناسب متجرك مساعد ذكاء اصطناعي للردود؟ | FIHRIST`, `Is an AI Assistant Right for Your Store Replies? | FIHRIST`),
    description: c(
      `دليل تشغيل مساعد ذكاء اصطناعي في متجرك: خطة أربعة أسابيع، أسئلة آمنة وأخرى خطرة، طريقة مراجعة الإجابات، وخطوات عند الخطأ.`,
      `A rollout guide for an AI assistant in your store: a four week plan, safe versus risky questions, how to audit answers, and what to do when it is wrong.`,
    ),
    h1: c(`هل يناسب متجرك مساعد ذكاء اصطناعي للردود؟`, `Is an AI assistant right for your store replies?`),
    lede: c(
      `المساعد الذكي ليس بديلًا عن فريقك، بل طبقة تجيب عن الأسئلة المتكررة وتترك القرارات لك. هذا دليل عملي لتحديد ما تفعّله وما تتركه للإنسان، وكيف تبدأ بأمان وتصحح عندما يخطئ.`,
      `An AI assistant is not a replacement for your team. It is a layer that answers repeated questions and leaves decisions to you. This is a practical guide to what you automate, what you leave to a person, how to start safely, and how to correct it when it is wrong.`,
    ),
    body: [
      { h: c(`ما يفعله المساعد وما لا يفعله`, `What an assistant does and does not do`) },
      { p: c(
        `الخلط الأكثر شيوعًا أن صاحب المتجر يتوقع موظفًا كاملًا، ثم يصاب بخيبة أمل. المساعد الذي يعمل من بيانات متجرك ليس بائعًا ولا مفاوضًا. هو طبقة أولى تجيب عن سؤال له إجابة مسجلة عندك، وتترك ما لا إجابة له لشخص يعرف المتجر.`,
        `The most common confusion is a store owner expecting a full employee, then feeling let down. An assistant that works from your store data is not a salesperson and not a negotiator. It is a first layer that answers questions whose answers you have on record, and leaves everything else to a person who knows the store.`,
      ) },
      { ul: [
        c(`يفعل: يجيب عن سعر معلن، وتوفر، وخيارات، ومواعيد عمل، وسياسة مكتوبة`, `It does: answer with a listed price, availability, options, opening hours, and a written policy`),
        c(`يفعل: يرد في وقت لا يوجد فيه أحد، بدل أن ينتظر العميل ساعات`, `It does: reply when nobody is around, instead of leaving the customer waiting for hours`),
        c(`لا يفعل: لا يقرر خصمًا، ولا يوافق على استثناء، ولا يعد بموعد لم تُحدده أنت`, `It does not: decide a discount, approve an exception, or promise a date you have not set`),
        c(`لا يفعل: لا يعرف ما لم يُسجَّل. إن كانت بياناتك قديمة فإجابته قديمة بنفس القدر`, `It does not: know what is not recorded. If your data is stale, its answer is just as stale`),
        c(`لا يفعل: لا يشعر بالغضب في رسالة العميل، ولا يعرف أن هذه المرة الثالثة التي يشتكي فيها`, `It does not: sense anger in a message, or know this is the third time this customer has complained`),
      ] },

      { h: c(`الأسئلة الآمنة للأتمتة`, `Questions that are safe to automate`) },
      { p: c(
        `السؤال الآمن هو الذي له إجابة واحدة صحيحة موجودة في بياناتك، ولا يترتب على الخطأ فيه خسارة كبيرة. ابدأ من هذه الفئة، فهي التي تعطي وقتًا للفريق بلا مخاطرة تُذكر.`,
        `A safe question has one correct answer that exists in your data, and a mistake in it costs little. Start with this group, because it gives the team time without meaningful risk.`,
      ) },
      { ol: [
        c(`السعر المعلن لصنف محدد، بشرط أن يكون السعر في البيانات هو السعر الفعلي`, `The listed price of a specific item, provided the price in your data is the real price`),
        c(`هل يوجد الصنف بمقاس أو لون معين، إن كان المخزون محدثًا بوحدات لا بأرقام عامة`, `Whether an item exists in a given size or color, if stock is kept in units and not as a general number`),
        c(`مواعيد العمل، والعنوان، وطريقة التواصل`, `Opening hours, address, and contact method`),
        c(`سياسة الاستبدال والإرجاع كما هي مكتوبة، بلا اجتهاد ولا استثناء`, `The exchange and return policy exactly as written, with no improvisation and no exceptions`),
        c(`طريقة الدفع المتاحة، وهل الدفع عند الاستلام متاح أم لا`, `Available payment methods and whether cash on delivery is offered`),
        c(`مدة التوصيل المعلنة كفترة، لا كوعد بتاريخ محدد`, `The stated delivery time as a window, never as a promise of a specific date`),
      ] },

      { h: c(`الأسئلة الخطرة التي تحتاج إنسانًا`, `Risky questions that need a person`) },
      { ul: [
        c(`الشكوى: "الطلب وصل متأخر" أو "القطعة تالفة". المساعد قد يجادل أو يعتذر بشكل يزيد الغضب`, `Complaints: "the order came late" or "the item is damaged". An assistant may argue or apologize in a way that fuels anger`),
        c(`الاستثناء: "هل يمكن إرجاع القطعة بعد انتهاء المدة؟" هذا قرار مالك لا قاعدة`, `Exceptions: "can I return it after the period?" That is an owner's decision, not a rule`),
        c(`التفاوض: أي طلب لخصم أو تجميع سعر أو هدية`, `Negotiation: any request for a discount, a bundle price, or a free item`),
        c(`الحالات الفردية: طلب مفقود، تحويل لم يظهر، مقاس غير متوفر ويريد بديلًا بموعد`, `Individual cases: a missing order, a transfer that did not show up, an unavailable size where they want a dated alternative`),
        c(`أسئلة لم تُسجَّل إجابتها: "هل يتحمل القماش الغسيل؟" إن لم تكن المعلومة موثقة فلا تجعلها تُخترع`, `Questions you never recorded: "will the fabric survive washing?" If the fact is not documented, do not let it be invented`),
        c(`أي محادثة فيها كلمة غضب أو تهديد بمقاطعة أو ذكر لتجربة سيئة سابقة`, `Any conversation containing anger, a threat to leave, or a mention of a past bad experience`),
      ] },
      { p: c(
        `قاعدة عملية للتفرقة: إن كانت الإجابة ستكون نفسها لأي عميل، فهي مرشحة للأتمتة. وإن كانت الإجابة تعتمد على هذا العميل تحديدًا أو على تقديرك، فهي لشخص من الفريق. القاعدة ليست دقيقة تمامًا، لكنها تمنع معظم الأخطاء المكلفة.`,
        `A practical rule of thumb: if the answer would be the same for any customer, it is a candidate for automation. If it depends on this particular customer or on your judgment, it belongs to a team member. The rule is not perfect, but it prevents most costly mistakes.`,
      ) },

      { h: c(`قبل التشغيل: جهّز بيانات المتجر`, `Before switching on: prepare your store data`) },
      { p: c(
        `المساعد يعكس بياناتك، فلا توجد طريقة تجعله أدق من رفّك. أصلح البيانات أولًا، وإلا ستنقل الأخطاء القديمة إلى العملاء بسرعة أكبر وبنبرة واثقة، وهذا أسوأ من عدم الرد.`,
        `The assistant mirrors your data, so there is no way to make it more accurate than your shelf. Fix the data first, otherwise you will deliver old errors to customers faster and in a more confident tone, which is worse than not replying at all.`,
      ) },
      { ul: [
        c(`الأسعار: صنف واحد بسعرين في مكانين مختلفين هو أول ما يجب حسمه`, `Prices: one item with two prices in two places is the first thing to settle`),
        c(`الخيارات: لكل مقاس ولون وحدته وسعره وكميته، لا رقم إجمالي واحد للصنف`, `Options: each size and color gets its own unit, price, and quantity, not one total for the item`),
        c(`السياسات: اكتب الاستبدال والإرجاع والتوصيل في جمل قصيرة قابلة للاقتباس حرفيًا`, `Policies: write exchange, return, and delivery as short sentences that can be quoted word for word`),
        c(`الأصناف الموقوفة: احذفها أو اكتب عليها بوضوح أنها غير متاحة، فلا يجيب المساعد عنها بثقة`, `Discontinued items: delete them or mark them clearly as unavailable, so the assistant does not answer about them confidently`),
        c(`الأسئلة الشائعة: اجمع آخر خمسين سؤالًا حقيقيًا من محادثاتك، واكتب لكل واحد إجابة معتمدة`, `Common questions: collect the last fifty real questions from your chats and write an approved answer for each`),
      ] },

      { h: c(`خطة أربعة أسابيع للتشغيل الآمن`, `A four week safe rollout plan`) },
      { p: c(
        `لا تشغّل المساعد على كل المحادثات في يوم واحد. الأسبوع الأول ليس عن المساعد أصلًا، بل عن بياناتك. التدرج يمنحك فرصة اكتشاف الخطأ قبل أن يراه العميل.`,
        `Do not switch the assistant on across all conversations in one day. Week one is not about the assistant at all, it is about your data. Going step by step gives you a chance to catch an error before a customer does.`,
      ) },
      { ol: [
        c(`الأسبوع الأول، تنظيف فقط: صحّح الأسعار والخيارات والسياسات، واكتب عشرين إجابة معتمدة. لا تفعّل شيئًا بعد.`, `Week one, cleaning only: fix prices, options, and policies, and write twenty approved answers. Turn nothing on yet.`),
        c(`الأسبوع الثاني، أسئلة السعر والتوفر فقط: المساعد يرد على هذه الفئة وحدها، وأنت تراجع كل محادثة في نهاية اليوم.`, `Week two, price and availability only: the assistant handles just this group, and you review every conversation at the end of the day.`),
        c(`الأسبوع الثالث، أوقات الذروة: اتركه يرد في ساعات الازدحام أو خارج ساعات العمل، مع بقاء المحادثات الحساسة للفريق.`, `Week three, peak hours: let it reply during busy hours or outside opening hours, while sensitive conversations stay with the team.`),
        c(`الأسبوع الرابع، القياس: قارن عدد الأسئلة التي انتهت بلا رد قبل التشغيل وبعده، وعدد الإجابات التي صحّحها الفريق.`, `Week four, measurement: compare how many questions ended unanswered before and after, and how many answers the team had to correct.`),
      ] },
      { p: c(
        `القرار في نهاية الشهر لا يكون "هل أعجبني؟" بل "هل قلّت الأسئلة المتروكة بلا رد، وهل بقيت الإجابات صحيحة؟". إن كان الجواب لا، فالمشكلة في البيانات أو في نطاق التفعيل، وليست في الفكرة نفسها.`,
        `The decision at the end of the month is not "did I like it?" but "did fewer questions go unanswered, and did the answers stay correct?" If the answer is no, the problem lies in the data or in how narrowly you enabled it, not in the idea itself.`,
      ) },

      { h: c(`متى يحوّل المحادثة إلى إنسان`, `When it should hand over to a person`) },
      { p: c(
        `قيمة المساعد الحقيقية تظهر في سرعة تحويله، لا في عدد إجاباته. مساعد يجيب عن كل شيء ولا يحوّل أبدًا أخطر من مساعد يقول "سأسأل صاحب المتجر وأرد عليك" في اللحظة المناسبة.`,
        `The real value of an assistant shows in how fast it hands over, not in how much it answers. An assistant that answers everything and never hands over is more dangerous than one that says "I will ask the store owner and get back to you" at the right moment.`,
      ) },
      { ul: [
        c(`عند أي شكوى أو ذكر لكلمة "تأخر" أو "تالف" أو "خطأ"`, `On any complaint or mention of late, damaged, or wrong`),
        c(`عند طلب خصم أو استثناء أو موعد تسليم محدد بالتاريخ`, `On a request for a discount, an exception, or a delivery date pinned to a day`),
        c(`عند سؤال لا يوجد له جواب في البيانات، ولو بدا بسيطًا`, `On a question with no answer in the data, however simple it looks`),
        c(`عند أي إشارة إلى أن العميل اشترى قبل ذلك وله تاريخ مع المتجر`, `On any sign that the customer bought before and has history with the store`),
        c(`عند طلب التحدث إلى شخص، بلا محاولة إقناعه بالبقاء مع المساعد`, `On a request to speak to a person, with no attempt to keep them with the assistant`),
      ] },
      { p: c(
        `ويجب أن يكون التحويل مصحوبًا بسياق: من العميل، وماذا سأل، وما تم الرد به، ومن أخذ المحادثة. التحويل بلا سياق يجبر العميل على إعادة كلامه، وهذا أسوأ من الانتظار قليلًا.`,
        `The handover should carry context: who the customer is, what they asked, what was already answered, and who picked it up. A handover without context forces the customer to repeat themselves, which is worse than waiting a little longer.`,
      ) },

      { h: c(`كيف تراجع الإجابات`, `How to audit the answers`) },
      { p: c(
        `المراجعة ليست قراءة كل شيء إلى الأبد، بل عيّنة منظمة في البداية ثم عيّنة أصغر بثقة أكبر. الهدف ليس إثبات أن المساعد جيد، بل العثور على الخطأ قبل العميل.`,
        `Auditing is not reading everything forever. It is a structured sample at the start, then a smaller sample as confidence grows. The goal is not to prove the assistant is good, but to find the error before a customer does.`,
      ) },
      { ul: [
        c(`عيّنة أول أسبوع: كل محادثة، بلا استثناء، لأن الحجم صغير والخطأ محتمل`, `First week sample: every conversation, with no exceptions, because volume is small and errors are likely`),
        c(`بعد ذلك: عشر محادثات في الأسبوع، من الأيام المختلفة، ومن أنواع أسئلة مختلفة`, `Afterwards: ten conversations a week, from different days and different question types`),
        c(`سجّل في كل مراجعة ثلاثة حقول: السؤال، الإجابة، وصح أو خطأ أو ناقص`, `Record three fields per audit: the question, the answer, and correct, wrong, or incomplete`),
        c(`كل خطأ يتكرر مرتين يجب أن يتحول إلى تعديل في البيانات أو في نطاق الأسئلة المسموح بها`, `Any error repeating twice must become a change in the data or in the allowed question scope`),
        c(`راجع أيضًا المحادثات التي انتهت بصمت، فهي المكان الذي يختبئ فيه الخطأ غير الملاحظ`, `Also review conversations that ended in silence, that is where unnoticed errors hide`),
      ] },
      { p: c(
        `مثال على ورقة مراجعة بسيطة: التاريخ، السؤال باختصار، ما أجاب به المساعد، الحكم، وما فعلته أنت. بعد شهر تكون عندك قائمة بالأخطاء المتكررة، وهي أثمن من أي انطباع عام.`,
        `An example of a simple audit sheet: date, question in brief, what the assistant answered, the verdict, and what you did. After a month you will have a list of recurring errors, which is worth more than any general impression.`,
      ) },

      { h: c(`ماذا تفعل عند إجابة خاطئة`, `What to do when the answer was wrong`) },
      { p: c(
        `الخطأ ليس نهاية التجربة، لكن طريقة التعامل معه هي التي تحدد إن كان العميل سيبقى. الترتيب المهم: صحّح للعميل أولًا، ثم أصلح السبب، ثم أوقف المساعد إن كان السبب غير واضح.`,
        `An error is not the end of the experiment, but how you handle it decides whether the customer stays. The order that matters: correct it with the customer first, then fix the cause, then switch the assistant off if the cause is still unclear.`,
      ) },
      { p: c(
        `مثال: عميل سأل عن سعر حقيبة، فأجاب المساعد بالسعر القديم لأن السعر تغيّر في النظام ولم يُحدَّث في البيانات التي يقرأ منها.`,
        `An example: a customer asked the price of a bag, and the assistant quoted the old price because the price had been changed in the shop but not updated in the data it reads from.`,
      ) },
      { ol: [
        c(`صحّح مع العميل: "السعر الصحيح هو [السعر]، وأعتذر عن الالتباس. هل تحب أكمّل الطلب بالسعر الصحيح؟" بلا تبرير طويل.`, `Correct it with the customer: "The correct price is [price], and I apologize for the confusion. Would you like me to complete the order at the correct price?" with no long explanation.`),
        c(`أصلح السبب: حدّث السعر في البيانات، وتحقق من الأصناف الأخرى التي تغيّر سعرها في الفترة نفسها.`, `Fix the cause: update the price in the data, and check other items whose price changed in the same period.`),
        c(`راجع النطاق: إن كان الخطأ من نوع سؤال لا يجب أن يجيب عنه المساعد، فاحجبه عن هذا النوع بدل الاعتماد على انتباهه.`, `Review the scope: if the error came from a question type the assistant should not answer, block it from that type instead of relying on its attention.`),
        c(`سجّل الحادثة: صنف، سؤال، إجابة، تصحيح. تكرارها مرتين يعني قرارًا، لا صدفة.`, `Log the incident: item, question, answer, correction. A second occurrence means a decision, not bad luck.`),
      ] },
      { p: c(
        `ولا تحاول إخفاء الخطأ عن العميل أو تبريره بأن "النظام قال". العميل تعامل مع متجرك، لا مع نظامك، والاعتذار القصير الواضح أرخص من جدال.`,
        `And do not hide the error from the customer or excuse it with "the system said so". The customer dealt with your store, not your system, and a short clear apology costs less than an argument.`,
      ) },

      { h: c(`أخطاء شائعة عند التشغيل`, `Common mistakes when rolling it out`) },
      { ul: [
        c(`التشغيل قبل تنظيف البيانات: أسرع طريقة لنشر أخطاء قديمة بنبرة واثقة`, `Switching on before cleaning the data: the fastest way to spread old errors in a confident tone`),
        c(`تفعيله على كل الأسئلة في اليوم الأول: يمنعك من معرفة مصدر الخطأ عند حدوثه`, `Enabling it on every question on day one: it hides where an error came from when one appears`),
        c(`تركه بلا مسار تحويل: عميل غاضب يدور في حلقة مغلقة يترك المتجر بصمت`, `Leaving it with no handover path: an angry customer in a closed loop leaves quietly`),
        c(`عدم إخبار العميل بأن الرد آلي: الصراحة تبني توقعًا صحيحًا، وتجعل تدخل الفريق طبيعيًا`, `Not telling the customer a reply is automated: honesty sets the right expectation and makes a team takeover normal`),
        c(`الحكم على التجربة من محادثة واحدة: قرار بهذا الحجم يحتاج أسبوعين على الأقل ورقمًا واحدًا تقارنه`, `Judging the experiment from one conversation: a decision this size needs at least two weeks and one number to compare`),
        c(`الاعتماد عليه في المتابعة الحساسة: من اشتكى أو طلب استردادًا يحتاج اسمًا بشريًا يتابع معه`, `Relying on it for sensitive follow-up: whoever complained or asked for a refund needs a human name to deal with`),
      ] },

      { h: c(`إذا حدث كذا افعل كذا`, `If this happens, do this`) },
      { ul: [
        c(`المساعد أجاب بسعر خطأ: صحّح للعميل في نفس المحادثة، ثم حدّث البيانات، ثم ابحث عن كل صنف تغيّر سعره حديثًا.`, `The assistant quoted a wrong price: correct it with the customer in the same conversation, then update the data, then find every item whose price changed recently.`),
        c(`المساعد وعد بموعد توصيل: أرسل تصحيحًا واحدًا واضحًا، وامنع هذه الفئة من الأسئلة حتى تكتب فترات محددة.`, `The assistant promised a delivery date: send one clear correction, and block that question type until you write fixed windows.`),
        c(`العميل كتب "أريد التحدث إلى شخص": حوّل فورًا بلا سؤال، وأرسل سياق المحادثة لمن استلمها.`, `The customer wrote "I want to talk to someone": hand over immediately with no questions, and pass the conversation context to whoever takes it.`),
        c(`العميل لم يفهم أن الرد آلي وطلب شيئًا غير ممكن: اعتذر بجملة واحدة، ووضّح من سيتابع، ولا تدعه يشرح المشكلة مرتين.`, `The customer did not realize the reply was automated and asked for something impossible: apologize in one sentence, say who will follow up, and do not make them explain twice.`),
        c(`تكرر خطأ في صنف واحد: أوقف المساعد عن هذا الصنف تحديدًا بدل إيقاف كل شيء أو ترك الخطأ يستمر.`, `The same error repeated on one item: remove that item from the assistant's scope instead of switching everything off or letting the error continue.`),
        c(`توقف المساعد أو تعطّل: لا تترك المحادثات مفتوحة. أغلق التفعيل وأرسل رسالة قصيرة للعملاء المنتظرين بأن الرد سيتأخر.`, `The assistant stopped or failed: do not leave conversations open. Turn it off and send a short message to waiting customers that replies will be delayed.`),
      ] },

      { h: c(`المساعد التحليلي سؤال مختلف`, `The analysis assistant is a different question`) },
      { p: c(
        `إلى جانب مساعد العملاء يوجد نوع آخر: مساعد يقرأ أرقام متجرك ويشرحها. هذا النوع مفيد حتى لو لم تفعّل الأول أبدًا، لأنه لا يتحدث مع العميل ولا يخاطره، بل معك.`,
        `Besides the customer assistant there is another kind: one that reads your store numbers and explains them. This kind is useful even if you never enable the first, because it does not talk to customers, it talks to you.`,
      ) },
      { p: c(
        `الخطر هنا مختلف: ليس إجابة عميل خاطئة، بل استنتاج خاطئ تبنيه عليه قرارًا. لذلك اطلب منه دائمًا ثلاثة أشياء: الرقم الذي يستند إليه، والفترة التي قارنها، وما لا تستطيع البيانات قوله. إن قال "المبيعات انخفضت لأن المنافس خفّض سعره" فاسأله: أي بيانات في متجرك تثبت ذلك؟ إن لم توجد، فالسبب غير معروف، وهذا جواب صحيح أيضًا.`,
        `The risk here is different: not a wrong answer to a customer, but a wrong conclusion you build a decision on. So always ask it for three things: the figure it relies on, the period it compared, and what the data cannot say. If it says "sales fell because a competitor cut prices", ask which of your own data proves that. If none exists, the cause is unknown, and that is a valid answer too.`,
      ) },
      { p: c(
        `القاعدة العامة للنوعين واحدة: أبقِ القرار عندك. الأداة تسرّع القراءة والرد، لكنها لا تعرف المتجر ولا تاريخه مع عميل بعينه، ولا تتحمل نتيجة القرار.`,
        `The general rule for both kinds is the same: keep the decision with you. A tool speeds up reading and replying, but it does not know the store, its history with a particular customer, or the consequences of a decision.`,
      ) },

      { h: c(`كيف يساعد FIHRIST؟`, `How FIHRIST helps`) },
      { p: c(
        `في FIHRIST يجمع الصندوق الموحد واتساب وماسنجر وإنستجرام والبريد والدردشة على الموقع، وتُربط كل محادثة بالعميل والمنتج والطلب، مع تعيين مسؤول وحالة، وتذكيرات متابعة يمكن إيقافها. المخزون يُسجَّل بوحدات للمقاسات والألوان والخيارات، ولكل وحدة سعرها وكميتها، ويخصم كل طلب الكمية المباعة، ويمكن طباعة رمز QR لتمييز الأصناف ومقارنة حركة المنتجات بين الفترات. الصلاحيات تُحدد لكل عضو. أما مساعد العملاء فيجيب من بيانات المتجر المسجلة فقط عند تفعيله، ويمكنك إبقاؤه مغلقًا والمتابعة يدويًا، ويستطيع فريقك متابعة أي محادثة والتدخل فيها، مع تذكير أن أي ذكاء اصطناعي قد يخطئ. ومساعد التحليل يشرح ما تدعمه البيانات فقط. الواجهة تعمل من المتصفح، وبالعربية والإنجليزية.`,
        `In FIHRIST, a unified inbox brings together WhatsApp, Messenger, Instagram, email, and web chat; each conversation links to the customer, product, and order; each can have an owner and a status; and follow-up reminders can be switched off. Stock is recorded as units for sizes, colors, and options, each unit with its own price and quantity, each order deducts the quantity sold, and you can print a QR code to identify items and compare item movement across periods. Permissions are set per member. The customer assistant answers from recorded store data only when enabled, you can keep it off and follow up manually, and your team can follow any conversation and step in, with the reminder that any AI can make mistakes. The analysis assistant explains only what the data supports. The interface runs in a browser, in Arabic and English.`,
      ) },
    ],
    faq: [
      {
        q: c(`هل يمكن للمساعد أن يرد على أسئلة الأسعار دون أخطاء؟`, `Can an assistant answer price questions without errors?`),
        a: c(
          `يمكن أن يكون دقيقًا إلى حد كبير إن كان السعر في بيانات المتجر هو السعر الفعلي دائمًا. الخطأ يأتي عادةً من مصدرين: سعر تغيّر ولم يُحدَّث، أو صنف له سعران في مكانين. لذلك القاعدة العملية أن تُحدَّث الأسعار في مكان واحد، وأن تُراجع بعد أي تغيير. لا يوجد ضمان كامل، فالتدخل البشري يبقى متاحًا.`,
          `It can be very accurate if the price in your store data is always the real price. Errors usually come from two sources: a price that changed and was not updated, or an item priced in two places. So the practical rule is to update prices in one place and recheck after any change. There is no full guarantee, which is why human takeover stays available.`,
        ),
      },
      {
        q: c(`كيف أخبر العميل أن الرد آلي دون أن يغادر المحادثة؟`, `How do I tell a customer the reply is automated without losing them?`),
        a: c(
          `جملة واحدة في أول رد تكفي، مثل "أنا مساعد المتجر، ويمكنني توصيلك بأحد أفراد الفريق في أي وقت". الأهم أن تكون صادقة وأن يجد العميل بابًا سهلًا للخروج نحو إنسان. التجربة العملية أن الصراحة تقلل الغضب عند الخطأ، لأن العميل يتوقع أن يتابع أحد.`,
          `One sentence in the first reply is enough, such as "I am the store assistant, and I can connect you to a team member at any time". What matters is honesty and an easy door out to a person. In practice, honesty reduces anger when an error happens, because the customer expects someone to follow up.`,
        ),
      },
      {
        q: c(`ما أقل قدر من البيانات يكفي لبدء التجربة؟`, `What is the minimum data needed to start?`),
        a: c(
          `لا تحتاج كل شيء، لكن تحتاج ثلاثة عناصر على الأقل: أسماء الأصناف بخياراتها، وأسعارها الحقيقية، وسياسة الاستبدال والتوصيل مكتوبة. ابدأ بعشرين صنفًا من الأكثر سؤالًا وأربعة أسئلة متكررة. التجربة الصغيرة على نطاق محدود تعطيك إشارة أوضح من انتظار بيانات كاملة.`,
          `You do not need everything, but you need at least three things: item names with their options, their real prices, and the exchange and delivery policy written down. Start with the twenty most asked about items and four common questions. A small trial on a narrow scope gives you a clearer signal than waiting for complete data.`,
        ),
      },
      {
        q: c(`هل يفيد المساعد في المتجر الصغير الذي لا يملك فريقًا؟`, `Does an assistant help a small store with no team?`),
        a: c(
          `يفيد أكثر في هذه الحالة بشرط أن يكون نطاقه ضيقًا. متجر يديره شخص واحد يخسر أسئلة كثيرة لأنه نائم أو مشغول، والمساعد يغطي هذه الفجوة بشرط أن يعيد المحادثات التي تحتاج قرارًا إلى مالكها. أما إن كان المساعد سيغطي كل شيء بلا مراجعة، فهو يضاعف المخاطرة لا يقللها.`,
          `It helps more in that case, provided its scope is narrow. A one person store loses many questions because the owner is asleep or busy, and an assistant covers that gap if it returns decisions to the owner. If it is left to cover everything with no review, it multiplies the risk rather than reducing it.`,
        ),
      },
      {
        q: c(`ماذا أفعل إن كان المساعد يكرر اعتذارًا طويلًا في كل محادثة؟`, `What if the assistant keeps giving a long apology in every conversation?`),
        a: c(
          `هذا عادةً يعني أن التعليمات التي تعمل عليها واسعة أكثر من اللازم، فيحاول تغطية الاحتمالات كلها. اضبط الأسلوب بحدود قصيرة: جملة اعتذار واحدة، ثم خطوة عملية واحدة، ثم يدع العميل يكمل. راجع بعدها عشر محادثات لتتأكد أن الطول لم يعد مشكلة.`,
          `That usually means the instructions it works from are too broad, so it tries to cover every possibility. Set the style with short limits: one apology sentence, then one practical step, then let the customer continue. Review ten conversations afterwards to confirm the length is no longer a problem.`,
        ),
      },
    ],
    related: ['reply-to-customers-faster-unified-inbox', 'sales-report-basics-for-store-owners'],
    solution: 'ai-sales-assistant',
  },
};
