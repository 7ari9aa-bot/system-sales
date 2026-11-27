// Blog articles, part 3. Two expanded guides for FIHRIST.
//   * Practical, step-by-step advice a store owner can use without FIHRIST.
//   * FIHRIST appears only in the final section, only with capabilities it really has.
//   * No invented statistics, studies, customers, prices or guarantees.
//   * No em dashes or en dashes anywhere.
// Body blocks: { h: heading } | { p: paragraph } | { ul: [items] } | { ol: [items] }

const c = (ar, en) => ({ ar, en });

export const POSTS_3 = {
  'follow-up-customers-who-went-quiet': {
    date: '2026-11-15',
    minutes: 8,
    title: c('كيف تتابع العملاء الذين توقفوا عن الرد | FIHRIST', 'How to Follow Up With Customers Who Went Quiet | FIHRIST'),
    description: c(
      'دليل عملي للمتابعة: متى ترسل، وماذا تقول في كل موقف، وجدول مواعيد، وقوالب رسائل، ومتى تتوقف دون إزعاج.',
      'A practical follow-up guide: when to send, what to say in each situation, a timing table, message templates, and when to stop.',
    ),
    h1: c('كيف تتابع العميل الذي توقف عن الرد', 'How to follow up with the customer who went quiet'),
    lede: c(
      'العميل الصامت ليس بالضرورة رافضًا. غالبًا انشغل، أو نسي، أو ينتظر قرارًا من طرف آخر. الفرق بين متابعة تعيد بيعًا ومتابعة تُفقد العميل هو التوقيت والسبب والصياغة، وهذا الدليل يرتب الثلاثة.',
      'A silent customer is not necessarily a no. Often they got busy, forgot, or are waiting on someone else. What separates a follow-up that wins the sale back from one that loses the customer is timing, reason, and wording. This guide puts the three in order.',
    ),
    body: [
      { h: c('لماذا يصمت العميل؟ أربعة أسباب مختلفة', 'Why does the customer go quiet? Four different reasons') },
      { p: c(
        'الصمت من الخارج شكل واحد: لا رد. لكن تحته أسباب مختلفة: عميل انشغل ونسي، وعميل ينتظر قرارًا من طرف آخر، وعميل وجد بديلًا ولم يجد طريقة ليقول ذلك، وعميل لم يفهم الخطوة التالية بعد السعر. كل سبب يحتاج رسالة مختلفة، ولهذا تفشل الرسالة الواحدة للجميع.',
        'From outside, silence looks like one thing: no reply. Under it are different reasons: a customer who got busy and forgot, one waiting on someone else, one who found an alternative and could not say so, and one who did not understand the next step after the price. Each needs a different message, which is why one message for everyone fails.',
      ) },
      { p: c(
        'مثال صغير: ثلاثة عملاء سألوا عن سعر حقيبة في يوم واحد. الأول انشغل بعد أول رسالة. الثاني ينتظر رأي شريكه. الثالث وجدها أرخص عند متجر آخر. إن أرسلت للثلاثة "هل ما زلت مهتمًا؟" فقد أرسلت رسالة تناسب واحدًا فقط، وهي غالبًا الرسالة التي لا تُقرأ.',
        'A small example: three customers asked the price of a bag on one day. The first got busy after the first message. The second is waiting for a partner. The third found it cheaper elsewhere. If you send all three "are you still interested?" you have sent a message that fits one of them, usually the one that goes unread.',
      ) },
      { p: c(
        'وسبب خامس يستحق الاعتراف: أنت. رسالة طويلة بلا سؤال، أو رد متأخر، أو سعر تغيّر مرتين في أسبوع، كلها تجعل العميل ينسحب بهدوء. قبل أن تلومه، اقرأ آخر رسالة أرسلتها.',
        'A fifth reason deserves admitting: you. A long message with no question, a late reply, or a price that changed twice in a week all make the customer withdraw quietly. Before you blame them, read your last message.',
      ) },

      { h: c('قبل أن ترسل: جهّز الملف في دقيقتين', 'Before you send: prepare the file in two minutes') },
      { p: c(
        'أكثر متابعة سيئة تحدث لأن البائع لا يتذكر ما وعد به. يرسل سؤالًا عامًا، فيرد العميل بسؤال لم يعد أحد يعرف جوابه، وتنتهي المحادثة. الدقيقتان قبل الرسالة توفّران محادثة كاملة.',
        'Most bad follow-ups happen because the seller no longer remembers what they promised. They send a general question, the customer replies with a question nobody can answer any more, and the conversation ends there. Two minutes before the message save a whole conversation.',
      ) },
      { ol: [
        c('اقرأ آخر عشر رسائل في المحادثة بسرعة، لا كل شيء.', 'Read the last ten messages in the chat quickly, not everything.'),
        c('اكتب في سطر واحد ما طلبه العميل وما وعدته به بالضبط.', 'Write in one line what the customer asked for and what exactly you promised.'),
        c('تحقق من توفر الصنف وسعره الآن، فالسعر القديم قد لا يكون صحيحًا اليوم.', 'Check that the item is available and its price today, because the old price may no longer be right.'),
        c('حدد هدف الرسالة: هل تريد حجزًا، أم إجابة على سؤال، أم إغلاقًا مهذبًا؟', 'Decide the goal of the message: a reservation, an answer to a question, or a polite close?'),
      ] },
      { p: c(
        'إن لم تجد جوابًا واضحًا عن هدف الرسالة فلا ترسلها اليوم. رسالة بلا هدف تُقرأ كإزعاج وتعلّم العميل أن يتجاهل رسائلك القادمة.',
        'If you cannot state the goal of the message clearly, do not send it today. A message with no goal reads as noise and teaches the customer to ignore your next ones.',
      ) },

      { h: c('القاعدة الأولى: لا متابعة بدون سبب', 'Rule one: no follow-up without a reason') },
      { p: c(
        '"هل من جديد؟" تنقل الجهد كله إلى العميل وتطلب منه أن يتذكر سبب المحادثة. الرسالة الجيدة تحمل شيئًا لا يعرفه: توفر، أو سعرًا مؤكدًا، أو خيارًا بديلًا، أو موعدًا. عندها يصبح الرد سهلًا، لأن الرد على معلومة أسهل من الرد على تذكير.',
        '"Any news?" moves all the effort to the customer and asks them to remember why the conversation existed. A good message carries something they do not know: availability, a confirmed price, an alternative, or a date. Replying becomes easy, because answering information is easier than answering a reminder.',
      ) },
      { ul: [
        c('توفر: المقاس أو اللون الذي سأل عنه عاد إلى المخزون.', 'Availability: the size or color they asked about is back in stock.'),
        c('سعر مؤكد أو متغير: أخبره بالجديد بنفسك بدل أن يكتشفه متأخرًا.', 'A confirmed or changed price: tell them yourself instead of letting them find out late.'),
        c('بديل: لون آخر أو مقاس قريب أو موديل يؤدي الغرض نفسه.', 'An alternative: another color, a close size, or a model that does the same job.'),
        c('موعد وصول: إن كان الصنف غير متوفر فالتاريخ المحدد سبب كافٍ للتواصل.', 'An arrival date: if the item is out of stock, a specific date is reason enough to reach out.'),
        c('إغلاق: إن لم يوجد سبب حقيقي، فالرسالة الأخيرة توضح أنك تتوقف.', 'A close: with no real reason, the last message makes clear you are stopping.'),
      ] },

      { h: c('جدول المتابعة: متى ترسل وماذا تتوقع', 'The follow-up schedule: when to send and what to expect') },
      { p: c(
        'المواعيد التالية نقطة بداية وليست قانونًا. عدّلها حسب دورة قرار منتجك: منتج صغير يُقرَّر في ساعة، وقطعة أثاث قد تستغرق أسبوعين. المهم أن يكون لكل محادثة تاريخ تالٍ مكتوب.',
        'The timings below are a starting point, not a law. Adjust them to your product cycle: a small item is decided within an hour, a piece of furniture can take two weeks. What matters is that every conversation has a written next date.',
      ) },
      { ol: [
        c('لحظة أول سؤال: سجّل الموعد قبل أن تُغلق المحادثة، فما لم يُكتب الآن لن يُتذكر غدًا.', 'At the first question: record the date before you close the chat, what is not written now will not be remembered tomorrow.'),
        c('بعد يوم واحد: للأسئلة السريعة التي انتهت بلا رد، برسالة قصيرة تحمل معلومة واحدة.', 'After one day: for quick questions that ended with no reply, a short message carrying one piece of information.'),
        c('بعد ثلاثة أيام: للطلبات التي وصلت إلى السعر أو المقاس ثم توقفت.', 'After three days: for orders that reached price or size and then stopped.'),
        c('بعد أسبوع: للمشتريات الأكبر التي تحتاج مشورة أو مقارنة بين خيارين.', 'After a week: for bigger purchases that need advice or a comparison between options.'),
        c('بعد يومين من التسليم: اطمئنان على المنتج نفسه، وليس عرضًا جديدًا.', 'Two days after delivery: a check on the product itself, not a new offer.'),
        c('بعد ثلاثين يومًا: للعميل الذي اشترى ورضي، بمناسبة شراء قريب.', 'After thirty days: for the happy customer, tied to a related purchase.'),
        c('بعد شهرين أو ثلاثة: للعميل القديم، بسبب جديد فقط.', 'After two or three months: for the old customer, with a new reason only.'),
      ] },
      { p: c(
        'هذا الجدول يوزّع المحادثات على الأيام بحيث تصل كل رسالة في وقتها، ولا يطلب حضورك اليومي في المحادثة نفسها. الخطأ الشائع أن تُرسل ثلاث رسائل في يومين ثم تختفي شهرًا.',
        'This schedule spreads conversations across days so each message lands on time, it does not ask you to be in the same chat daily. The common mistake is three messages in two days then a month of silence.',
      ) },

      { h: c('قوالب رسائل حسب الموقف', 'Message templates by situation') },
      { p: c(
        'القوالب التالية مسودات، غيّر كلمة أو كلمتين حتى تبدو بصوتك. الأهم أن تختار القالب الذي يناسب الموقف، فالقالب الجيد في الموقف الخطأ يضر أكثر من رسالة بسيطة في موضعها.',
        'The templates below are drafts, change a word or two so they sound like you. Most important is picking the one that fits the situation, a good template in the wrong place does more harm than a plain message in the right one.',
      ) },
      { ul: [
        c('صمت بعد السعر: "مرحبًا، سألت عن الحقيبة السوداء. تحب أوضح أي تفصيلة قبل أن تقرر؟ وإن كان السعر هو المشكلة فأخبرني، عندي أكثر من خيار."', 'Silence after the price: "Hi, you asked about the black bag. Would you like me to clarify any detail before you decide? And if the price is the issue, tell me, I have more than one option."'),
        c('توفر عاد: "المنتج الذي سألت عنه رجع للمخزون اليوم. هل أحجز لك الكمية قبل أن تنتهي؟"', 'Back in stock: "The item you asked about came back today. Shall I hold the quantity for you before it goes?"'),
        c('بعد وعد: "كما وعدتك، وصلتني التفاصيل. المتوفر حاليًا مقاسان، والسعر كما أخبرتك. تحب أجهز الطلب؟"', 'After a promise: "As promised, the details came through. Two sizes are available now, at the price I gave you. Shall I prepare the order?"'),
        c('تسهيل القرار: "إن كان القرار صعبًا، أقدر أحجز لك القطعة يومين بدون دفع. تحب أعملها؟"', 'Making the decision easier: "If the decision is hard, I can hold the piece for you for two days with no payment. Would you like that?"'),
        c('مشتريات أكبر: "قبل أن تقرر، سؤال واحد يساعدني أرشح لك الأنسب: هل الاستخدام يومي أم لمناسبة؟"', 'Bigger purchases: "Before you decide, one question helps me recommend the right one: is this for daily use or for an occasion?"'),
        c('بعد التسليم: "وصل الطلب؟ أردت أتأكد أن المقاس مناسب، وإن كان فيه أي مشكلة أخبرني اليوم."', 'After delivery: "Did the order arrive? I wanted to make sure the size is right, and if there is any problem tell me today."'),
        c('إعادة تنشيط: "مرحبًا، وصلت تشكيلة قريبة من الذي اشتريته قبل. تحب أرسل لك الصور؟"', 'Reactivation: "Hi, a new collection arrived close to what you bought before. Would you like me to send photos?"'),
        c('اعتذار عن تأخرنا: "آسف على التأخير في الرد. راجعت طلبك الآن، والوضع كذا بالضبط. تحب نكمل؟"', 'Apologizing for our delay: "Sorry for the late reply. I reviewed your order now, and here is exactly where it stands. Shall we continue?"'),
        c('إغلاق مهذب: "لم يصلني ردك، وأفترض أن الوقت غير مناسب حاليًا. سأتوقف عن المتابعة، وإن احتجت شيئًا لاحقًا أرسل لي في أي وقت."', 'A polite close: "I did not hear back, so I assume the timing is not right. I will stop following up, and if you need anything later, message me any time."'),
      ] },
      { p: c(
        'الرسالة الأخيرة هي الأهم، لأنها تحدد كيف يتذكرك العميل بعد شهر. إغلاق محترم يجعله يعود بنفسه عند أول حاجة، أما الصمت المتبادل فيتركه يظن أنك فقدت الاهتمام.',
        'The last template matters most, because it decides how the customer remembers you a month later. A respectful close brings them back on their own at the first need, while mutual silence leaves them thinking you lost interest.',
      ) },

      { h: c('النبرة: كيف تكتب رسالة لا تبدو إلحاحًا', 'Tone: how to write a message that does not feel pushy') },
      { p: c(
        'الإلحاح ليس في عدد الرسائل فقط، بل في شكلها. رسالة طويلة فيها ثلاثة أسئلة واعتذاران تبدو أشد من ثلاث رسائل قصيرة. القواعد التالية بسيطة وأثرها واضح في نسبة الرد.',
        'Pushiness is not only about how many messages you send, it is about their shape. A long message with three questions and two apologies feels heavier than three short ones. The rules below are simple and clearly affect replies.',
      ) },
      { ul: [
        c('من جملة إلى ثلاث جمل كحد أقصى. الرسالة الطويلة تُقرأ كضغط، والقصيرة تُقرأ كخدمة.', 'One to three sentences at most. A long message reads as pressure, a short one reads as service.'),
        c('سؤال واحد فقط. سؤالان في رسالة واحدة يعنيان غالبًا صفر رد، لأن العميل يجيب على الأسهل ويترك الباقي.', 'One question only. Two questions in one message usually mean zero replies, because the customer answers the easier one and leaves the rest.'),
        c('لا تعتذر ثلاث مرات. اعتذار واحد عند وجود خطأ حقيقي، ثم امضِ إلى الموضوع.', 'Do not apologize three times. One apology when there was a real mistake, then move to the point.'),
        c('اذكر تفصيلة تخصه: المقاس، اللون، اسم المنتج. التفصيلة تقول إنك تتذكره، لا إنك ترسل للجميع.', 'Mention a detail that belongs to them: the size, the color, the product name. The detail says you remember them, not that you are messaging everyone.'),
        c('اترك مخرجًا واضحًا: "إن لم يكن مناسبًا الآن فأخبرني وأتوقف". هذا يقلل إحساس العميل بأنه مطارَد.', 'Leave a clear exit: "if now is not the right time, tell me and I will stop". This reduces the feeling of being chased.'),
        c('لا تبدأ بالخصم. الخصم في أول متابعة يعلّم العميل أن يتجاهلك ليحصل على سعر أقل.', 'Do not open with a discount. A discount on the first follow-up teaches the customer to ignore you in order to get a lower price.'),
      ] },
      { p: c(
        'قارن: "هل تريد إكمال الطلب؟" تطلب قرارًا من عميل بلا تفاصيل كافية. أما "سألت عن الحقيبة السوداء، عندي منها مقاسان وأقدر أحجز لك واحدًا يومين، تحب أشوف المتوفر؟" فتعطيه خطوة صغيرة ومعلومة جديدة.',
        'Compare: "Are you completing the order?" asks for a decision from someone without enough details. "You asked about the black bag, it comes in two sizes and I can hold one for two days, want me to check what is available?" gives a small step and new information.',
      ) },

      { h: c('متى تتوقف: قاعدة المحاولات الثلاث', 'When to stop: the three attempts rule') },
      { p: c(
        'المتابعة الجيدة محدودة. القاعدة العملية: ثلاث محاولات، كل واحدة بسبب مختلف، ثم توقف. ثلاث رسائل بالمعنى نفسه في أسبوع لا تعني أنك مجتهد، بل أنك تضغط، والنتيجة عادة حجب أو تجاهل دائم.',
        'Good follow-up is limited. The practical rule: three attempts, each with a different reason, then stop. Three messages saying the same thing in a week does not mean you are diligent, it means you are pushing, and the result is usually a block.',
      ) },
      { ul: [
        c('طلب العميل صراحة أن تتوقف: يُحترم فورًا وبلا نقاش ولا محاولة أخيرة.', 'The customer explicitly asks you to stop: respect it immediately, with no discussion and no final attempt.'),
        c('ثلاث محاولات بأسباب مختلفة بلا أي رد، ولو بكلمة.', 'Three attempts with different reasons and no reply at all, not even one word.'),
        c('رفض السعر مرتين: لا تكرر العرض نفسه، فالرفض هنا واضح.', 'Two refusals on price: do not repeat the same offer, the refusal is clear.'),
        c('قال إنه اشترى من مكان آخر: أشكره واترك الباب مفتوحًا بلا تلميح.', 'They say they bought elsewhere: thank them and leave the door open without a hint.'),
        c('مر شهر بلا سبب جديد: الصمت الطويل يحتاج مناسبة، لا تذكيرًا.', 'A month passed with no new reason: long silence needs an occasion, not a reminder.'),
      ] },
      { p: c(
        'التوقف ليس حذفًا للعميل. اجعله "غير نشط" مع تاريخ آخر تواصل وسبب الصمت إن عرفته. والعودة تكون بسبب حقيقي: توفر، أو منتج جديد، أو موسم يخصه.',
        'Stopping is not deleting the customer. Mark them "inactive" with the date of last contact and the reason for silence if you know it. Coming back needs a real reason: availability, a new product, or a season that concerns them.',
      ) },

      { h: c('أخطاء شائعة وكيف تصلحها', 'Common mistakes and how to fix them') },
      { ul: [
        c('الرسالة نفسها للجميع: اكتب ثلاثة قوالب فقط، وخصص كل واحد باسم العميل والمنتج الذي سأل عنه.', 'The same message for everyone: keep only three templates and personalize each with the name and the product asked about.'),
        c('المتابعة على قناة واحدة: من قرأ ولم يرد على واتساب قد يرد على مكالمة قصيرة.', 'Following up on one channel only: someone who read and ignored WhatsApp may answer a short call.'),
        c('البدء بالخصم: ابدأ بالمعلومة، واترك السعر للتفاوض إن سأل هو.', 'Opening with a discount: open with information and leave price negotiation for when they raise it.'),
        c('الوعد بلا تاريخ: "سأعود إليك" يجب أن تصبح "سأرسل لك يوم الثلاثاء".', 'A promise with no date: "I will get back to you" should become "I will send it on Tuesday".'),
        c('ترك المتابعة لآخر اليوم: آخر اليوم أول ما يُلغى عند الزحمة. خصص أول عشر دقائق.', 'Leaving follow-up to the end of the day: it is the first thing cancelled when busy. Use the first ten minutes.'),
        c('متابعة العميل بعد الشراء بأسلوب البيع: بعد التسليم اسأل عن الرضا، لا عن طلب جديد.', 'Following up after a purchase with a sales pitch: after delivery ask about satisfaction, not about another order.'),
        c('نسيان سبب المتابعة: دوّن السبب في السجل، وإلا تحولت الرسالة إلى تذكير عام بلا قيمة.', 'Forgetting the reason: log the reason, otherwise the message turns into a valueless generic reminder.'),
      ] },

      { h: c('إذا حدث كذا فافعل كذا', 'If this happens, do this') },
      { ul: [
        c('إذا لم يرد بعد محاولتين: أرسل الإغلاق المهذب، وحدد تاريخًا للعودة عند أول سبب جديد حقيقي.', 'If there is no reply after two attempts: send the polite close and set a date to return when there is a real new reason.'),
        c('إذا قال "غالي": لا تخفض فورًا. اسأل: غالي مقارنة بماذا؟ ثم اقترح خيارًا أصغر أو أبسط إن كان موجودًا.', 'If they say "too expensive": do not cut the price at once. Ask what they are comparing it to, then suggest a smaller or simpler option if you have one.'),
        c('إذا قال "سأرد عليك": اسأله عن موعد تقريبي، واقترح أنت موعدًا، ثم سجّل التاريخ الذي وافق عليه.', 'If they say "I will get back to you": ask for a rough date, suggest one yourself, then record the date they agreed to.'),
        c('إذا لم يقرأ أو حجبك: لا تحاول من رقم آخر. هذا يفسد الثقة، والاحترام أرخص من بيعة واحدة.', 'If the message stays unread or you are blocked: do not try from another number. It destroys trust, and respect costs less than one sale.'),
        c('إذا عاد بعد ثلاثة أسابيع: ابدأ من حيث توقف، ولا تسأله "هل تتذكر طلبك؟"، فهذا يجعله يبدأ من الصفر.', 'If they return after three weeks: start where you stopped, and do not ask "do you remember your order?", that makes them start from scratch.'),
        c('إذا اشتكى من منتج وصل: المتابعة تصبح حل مشكلة. استمع، واعرض إصلاحًا أو استبدالًا، ثم عد للبيع في وقت آخر.', 'If they complain about a delivered item: the follow-up becomes problem solving. Listen, offer a fix or replacement, then return to selling later.'),
        c('إذا سأل سؤالًا لا تعرفه: قل "سأتأكد وأرد قبل نهاية اليوم"، واحترم الموعد حتى لو لم تجد جوابًا.', 'If they ask something you do not know: say "I will check and reply today", and keep that even if you find no answer.'),
      ] },

      { h: c('التنظيم: عشر دقائق كل صباح', 'The routine: ten minutes every morning') },
      { ol: [
        c('افتح قائمة "متابعة اليوم" قبل المحادثات الجديدة.', 'Open the "follow up today" list before new chats.'),
        c('رتّبها بالأقدم أولًا، فمن انتظر أربعة أيام أولى ممن انتظر ساعة.', 'Sort oldest first, someone who waited four days comes before one who waited an hour.'),
        c('أرسل خمسًا إلى عشر رسائل بجودة، لا ثلاثين رسالة مستعجلة.', 'Send five to ten good messages, not thirty rushed ones.'),
        c('بعد كل رسالة حدّث الحالة: تنتظر رد العميل، أو تنتظر ردنا، أو مغلقة.', 'After each message update the status: waiting for the customer, waiting for us, or closed.'),
        c('أغلق أي بند بلا سبب واضح، وأعد جدولته عند وجوده.', 'Close any item with no clear reason and reschedule it when one appears.'),
      ] },
      { p: c(
        'قائمة بسيطة تحتاج ستة حقول: الاسم، آخر تواصل، ما طلبه، سبب المتابعة القادمة، تاريخها، والحالة. جدول واحد يكفي، والأهم أن يُحدَّث في اليوم نفسه لا في نهاية الأسبوع.',
        'A simple list needs six fields: name, last contact, what they asked for, the reason for the next follow-up, its date, and the status. One sheet is enough, and what matters is updating it the same day, not at the end of the week.',
      ) },
      { p: c(
        'قائمة تحقق قبل كل إرسال: هل فيها معلومة أو خيار؟ هل فيها سؤال واحد؟ هل ذكرت تفصيلة تخصه؟ هل فيها مخرج واضح؟ إن كان جوابك "لا" على واحدة منها، أعد الكتابة.',
        'A checklist before every send: does it carry information or a choice? One question? A detail that belongs to them? A clear exit? If you answered "no" to any of these, rewrite it.',
      ) },

      { h: c('قياس بسيط: هل المتابعة تعمل؟', 'A simple check: is follow-up working?') },
      { p: c(
        'لا تحتاج تقارير معقدة. كل أسبوعين، عُدّ ثلاثة أرقام: كم متابعة أرسلت، كم رد وصل، وكم ردًا تحول إلى طلب. هذه الأرقام تكفي لتعرف أين المشكلة: في الصياغة أم التوقيت أم العرض.',
        'You do not need complex reports. Every two weeks, count three numbers: how many follow-ups you sent, how many replies arrived, and how many turned into an order. These are enough to see where the problem is: wording, timing, or the offer.',
      ) },
      { ul: [
        c('ردود قليلة ورسائل كثيرة: الصياغة طويلة، أو التوقيت متأخر، أو الرسالة بلا سبب.', 'Few replies, many messages: wording too long, timing too late, or no reason in the message.'),
        c('ردود كثيرة وطلبات قليلة: المشكلة في السعر أو في العرض أو في طريقة إتمام الطلب، لا في المتابعة.', 'Many replies and few orders: the problem is the price, the offer, or the way the order is completed, not the follow-up.'),
        c('الرد يأتي دائمًا بعد الثالثة: ابدأ بها، ووفّر الأوليين.', 'The reply always comes after the third: start there and save the first two.'),
      ] },
      { p: c(
        'غيّر شيئًا واحدًا في كل مرة. إن غيّرت التوقيت والصياغة والعرض معًا فلن تعرف أيها نجح.',
        'Change one thing at a time. If you change timing, wording, and offer together you will not know which one worked.',
      ) },

      { h: c('أين تساعدك أداة مثل FIHRIST؟', 'Where a tool like FIHRIST helps') },
      { p: c(
        'كل ما سبق يمكن تنفيذه بدفتر وجدول وانضباط، وبهذه الطريقة ننصح بالبدء. لكن مع كثرة المحادثات يصبح ربط كل عميل بسجله ومواعيده عملًا يدويًا مرهقًا.',
        'Everything above can be done with a notebook, a sheet, and discipline, that is the way we recommend starting. But with many conversations, linking every customer to their record and dates becomes tiring manual work.',
      ) },
      { p: c(
        'في FIHRIST تجتمع محادثات واتساب وماسنجر وإنستغرام والبريد والدردشة على الموقع في صندوق واحد، وكل محادثة مرتبطة بالعميل والمنتج والطلب، مع مسؤول وحالة. يمكنك ضبط تذكير أو قاعدة متابعة، وكل القواعد قابلة للإيقاف، فتبقى أنت المتحكم في ما يُرسَل. الواجهة تعمل بالعربية والإنجليزية.',
        'In FIHRIST, WhatsApp, Messenger, Instagram, email, and web chat sit in one inbox, and each conversation is linked to the customer, product, and order, with an owner and a status. You can set a reminder or a follow-up rule, and every rule can be turned off, so you stay in control of what is sent. The interface works in Arabic and English.',
      ) },
      { p: c(
        'الأداة تنظم القائمة والمواعيد، لكنها لا تكتب الرسالة بدلًا منك ولا تعرف متى يكون العميل مشغولًا. الحكم على النبرة والموقف يبقى لك.',
        'The tool organizes the list and the dates, but it does not write the message for you and does not know when the customer is busy. Judging tone and situation stays with you.',
      ) },
    ],
    faq: [
      {
        q: c('كم مرة أتابع العميل قبل أن أتوقف؟', 'How many times should I follow up before stopping?'),
        a: c(
          'مرتان أو ثلاث محاولات تكفي في معظم الحالات، بشرط أن تحمل كل محاولة سببًا مختلفًا: توفر، أو معلومة، أو خيارًا بديلًا. إن كانت المحاولات الثلاث بالمعنى نفسه فهي رسالة واحدة مكررة، والتوقف بعدها أفضل للعلاقة. بعد التوقف اجعل العميل غير نشط، وعد إليه عند سبب جديد حقيقي لا عند مرور الوقت فقط.',
          'Two or three attempts is enough in most cases, provided each one carries a different reason: availability, information, or an alternative. If all three say the same thing they are one message repeated, and stopping is better for the relationship. After stopping, mark the customer inactive and return with a real new reason, not just because time passed.',
        ),
      },
      {
        q: c('هل أرسل المتابعة في اليوم نفسه أم أنتظر؟', 'Should I follow up the same day or wait?'),
        a: c(
          'إن كان المنتج سريع القرار ووقت العميل يسمح، فانتظر يومًا واحدًا على الأقل، لأن المتابعة في نفس الساعة تبدو كضغط. أما إن كان العميل قد سأل سؤالًا محددًا ولم تحصل على جوابه بعد، فأرسل الجواب في نفس اليوم لأنه استكمال للخدمة لا متابعة. القاعدة أن تفرق بين إكمال معلومة ناقصة وبين تذكير بقرار لم يُتخذ.',
          'If the item is a quick decision and the customer has time, wait at least one day, because following up within the hour feels like pressure. But if the customer asked a specific question and you do not have the answer yet, send it the same day because that completes the service rather than chasing it. The rule is to separate completing missing information from reminding someone about a decision they have not made.',
        ),
      },
      {
        q: c('ماذا أكتب لعميل سأل عن السعر ثم اختفى؟', 'What should I write to a customer who asked the price and then vanished?'),
        a: c(
          'اكتب جملة قصيرة فيها معلومة جديدة وسؤال واحد. مثال: "سألت عن الحقيبة السوداء. عندي منها مقاسان، وأقدر أحجز لك واحدًا يومين. تحب أشوف المتوفر؟" لا تبدأ بالخصم ولا بجملة "هل ما زلت مهتمًا" وحدها، لأنها تنقل الجهد إلى العميل ولا تخبره بشيء. إن لم يرد، أرسل محاولة ثانية بسبب مختلف ثم أغلق بلطف.',
          'Write one short message with new information and a single question. For example: "You asked about the black bag. It comes in two sizes and I can hold one for you for two days. Want me to check what is available?" Do not open with a discount or with "are you still interested" alone, because it moves the effort to the customer and tells them nothing. If there is no reply, send a second attempt with a different reason, then close politely.',
        ),
      },
      {
        q: c('هل الخصم طريقة مناسبة لإعادة العميل الصامت؟', 'Is a discount a good way to bring back a quiet customer?'),
        a: c(
          'الخصم في أول متابعة يعلّم العميل أن يتجاهلك ليحصل على سعر أقل، ويقلل قيمة المنتج في عينه. الأفضل أن تبدأ بمعلومة أو خيار أو تسهيل في القرار، مثل حجز بدون دفع لمدة محددة. إن كان السعر هو السبب الحقيقي فسيسأل عنه أو سيقارن، وعندها يكون الخصم أو الخيار الأرخص منطقيًا وليس مجاملة.',
          'A discount on the first follow-up teaches the customer to ignore you in order to get a lower price, and it lowers the value of the product in their eyes. Better to start with information, an option, or an easier decision, such as a free hold for a set period. If price is the real reason they will raise it or compare, and then a discount or a cheaper option is a logical answer rather than a gift.',
        ),
      },
      {
        q: c('كيف أتابع عميلًا قديمًا لم يشتر منذ شهور دون أن أزعجه؟', 'How do I follow up with an old customer who has not bought in months without annoying them?'),
        a: c(
          'اربط الرسالة بسبب يخصه: منتج قريب من الذي اشتراه، أو توفر صنف كان يسأل عنه، أو موسم يستخدم فيه ما اشتراه. رسالة واحدة كل فترة طويلة أفضل من رسائل متكررة بلا مناسبة. واجعل الخروج سهلًا بعبارة مثل "إن لم يكن الوقت مناسبًا فأنا هنا عندما تحتاج"، ثم لا تعاود الاتصال قبل أن يظهر سبب جديد.',
          'Tie the message to a reason that concerns them: an item close to what they bought, the return of something they asked about, or a season in which they use what they bought. One message every long while is better than repeated messages with no occasion. Make the exit easy with a line like "if the timing is not right, I am here when you need me", then do not reach out again until a new reason appears.',
        ),
      },
    ],
    related: ['crm-vs-order-log-difference', 'how-to-sell-on-whatsapp-organized'],
    solution: 'sales-crm-for-stores',
  },

  'prevent-overselling-and-stockouts': {
    date: '2026-11-15',
    minutes: 7,
    title: c('كيف تتجنب بيع منتج نفد من المخزون | FIHRIST', 'How to Avoid Selling Items That Are Out of Stock | FIHRIST'),
    description: c(
      'لماذا تبيع منتجًا غير متوفر؟ أسباب وحلول: رقم واحد لكل خيار، الحجز عند الاتفاق، حدود إعادة الطلب، وقوالب اعتذار.',
      'Why do stores sell items they no longer have? Causes and fixes: one number per option, reserving at agreement, reorder points, and apology templates.',
    ),
    h1: c('كيف تتجنب بيع منتج نفد من المخزون', 'How to avoid selling an item that is out of stock'),
    lede: c(
      'أسوأ لحظة في البيع أن تعتذر لعميل وافق على طلب لم يعد موجودًا. المشكلة نادرًا ما تكون في سوء النية، فهي غالبًا رقم قديم، أو خيار غير مفصول، أو وعد قُطع قبل أن يُحجز. هذا الدليل يعالج الأسباب واحدًا واحدًا.',
      'The worst moment in selling is apologizing to a customer who agreed on an order that no longer exists. The problem is rarely bad intent: it is usually an old number, an option that was never separated, or a promise made before anything was reserved. This guide treats the causes one by one.',
    ),
    body: [
      { h: c('الفرق بين ما تملكه وما تستطيع بيعه', 'The difference between what you own and what you can sell') },
      { p: c(
        'هنا يبدأ معظم الخطأ. الرقم الذي في ذهنك ليس الكمية التي تستطيع بيعها. ما تستطيع بيعه هو ما تملكه، ناقص ما وعدت به غيرك، ناقص التالف، ناقص ما هو محجوز لطلب قائم. من يبيع من الرقم الأول يبيع مرتين وهو لا يدري.',
        'This is where most of the mistake starts. The number in your head is not the quantity you can sell. What you can sell is what you own, minus what you promised someone else, minus what is damaged, minus what is held for an existing order. Whoever sells from the first number sells twice without knowing it.',
      ) },
      { ul: [
        c('الكمية الموجودة: كل ما في المخزن أو الرف، بما فيه المحجوز.', 'Quantity on hand: everything in the storeroom or on the shelf, including what is reserved.'),
        c('الكمية المحجوزة: ما وُعد به عميل ولم يُسلَّم بعد.', 'Reserved quantity: what was promised to a customer and not yet delivered.'),
        c('الكمية المتاحة: الموجودة ناقص المحجوز ناقص التالف. هذا هو الرقم الذي تتكلم منه.', 'Available quantity: on hand minus reserved minus damaged. This is the number you speak from.'),
      ] },
      { p: c(
        'مثال صغير: عندك ست قطع سوداء مقاس M. عميل وافق على قطعتين ولم يُستلما بعد، وقطعة تالفة لم تُسجَّل. المتاح فعليًا ثلاث قطع، لا ست. إن لم تكن هذه الحسبة واضحة في السجل فستبيع القطعتين مرتين، وسيكتشف الخطأ العميل لا أنت.',
        'A small example: you have six black pieces in size M. A customer agreed on two that have not been delivered, and one piece is damaged but was never recorded. The real available number is three, not six. If this calculation is not clear in the record you will sell those two pieces twice, and the customer will discover the error, not you.',
      ) },

      { h: c('لماذا يحدث البيع الزائد؟ خمسة أسباب حقيقية', 'Why does overselling happen? Five real causes') },
      { ol: [
        c('البيع يُسجَّل متأخرًا، فيبقى الرقم قديمًا ساعات أو يومًا، وأنت تبيع من رقم لم يُحدَّث.', 'Sales are recorded late, so the number stays stale for hours or a day, and you sell from a number that was never updated.'),
        c('الصنف موجود في أكثر من مكان، في متجر وأمامك في محادثة وفي الكاشير، دون رقم واحد مشترك بينها.', 'The item exists in more than one place, in the shop, in front of you in a chat, and at the cashier, with no single shared number.'),
        c('المقاسات والألوان مختلطة في سطر واحد، فتظن أن عندك عشرين قطعة وعندك عشرون من مقاس واحد فقط.', 'Sizes and colors are merged into one line, so you think you have twenty pieces when you have twenty of one size only.'),
        c('لا يوجد حد ينبهك قبل النفاد، فتعرف أن الصنف انتهى في اللحظة التي يطلبه عميل.', 'No level warns you before it runs out, so you learn an item is gone the moment a customer asks for it.'),
        c('الوعد بالحجز غير مكتوب، فتعده لعميل وتتركه متاحًا للعميل التالي.', 'A hold is promised but not written, so you give it to one customer and leave it available for the next.'),
      ] },
      { p: c(
        'أربعة من الأسباب الخمسة ليست تقنية، بل عادات يومية: التسجيل لاحقًا، والوعد دون تسجيل، وعدم فصل المقاسات. الحل الأول هنا سلوكي قبل أن يكون برمجيًا.',
        'Four of the five causes are not technical, they are daily habits: recording later, promising without writing, not separating sizes. The first fix is behavioural before it is software.',
      ) },

      { h: c('الخطوة 1: اجعل الوحدة أصغر شيء تبيعه', 'Step 1: make the unit the smallest thing you sell') },
      { p: c(
        'لا تسجّل "قميص أزرق: 20". سجّل "قميص أزرق M" و"قميص أزرق L" و"قميص أزرق XL" كوحدات منفصلة. نفس القاعدة تنطبق على اللون، وعلى الخيار إن كان له سعر مختلف، وعلى العبوة إن كانت تُباع بأحجام. الوحدة ليست المنتج، بل النسخة التي يطلبها العميل بالاسم.',
        'Do not record "blue shirt: 20". Record "blue shirt M", "blue shirt L", and "blue shirt XL" as separate units. The same rule applies to color, to any option with a different price, and to packaging sold in different sizes. The unit is not the product, it is the version the customer asks for by name.',
      ) },
      { p: c(
        'الاختبار العملي: إن كان العميل قد يقول "أريد مقاساً آخر" بعد أن تبيع له، فهذا سطر مختلف. وإن كان المقاس أو اللون يؤثر في السعر فالسبب يتضاعف، لأنك لا تخطئ في الكمية فقط بل في المبلغ أيضًا.',
        'The practical test: if the customer might say "I want another size" after you sell to them, that needs its own line. If the size or color changes the price the reason doubles, because you are wrong about the quantity and the money at once.',
      ) },
      { p: c(
        'انتبه إلى الأطقم والمنتجات المركبة. طقم من قطعتين يستهلك قطعتين من مخزون مكوناته. إن كنت تبيع القطعة منفصلة والطقم معًا، فكل بيع طقم يخصم من كل مكوّن، وإلا وصلت إلى طقم لا تستطيع تجميعه وأنت تظن أن مكوناته موجودة.',
        'Watch out for sets and bundles. A two piece set consumes two pieces of its component stock. If you sell the piece separately and the set together, every set sale must deduct from each component, otherwise you reach a set you cannot assemble while thinking its parts are there.',
      ) },

      { h: c('الخطوة 2: رقم واحد مشترك بين كل القنوات', 'Step 2: one shared number across every channel') },
      { p: c(
        'إن كنت تبيع من واتساب، ومن الكاشير في المتجر، ومن صفحة على الإنترنت، فكل قناة يجب أن ترى الكمية نفسها. عندما تنسخ الأرقام يدويًا بين الأماكن، تصبح النسخة الأقدم هي التي تبيع، وهي لا تعرف ما حدث في الأماكن الأخرى.',
        'If you sell from WhatsApp, from the cashier in the shop, and from an online page, every channel must see the same quantity. When you copy numbers by hand between places, the oldest copy does the selling, and it does not know what happened elsewhere.',
      ) },
      { ul: [
        c('اختر مكانًا واحدًا يعتبر "المصدر"، وكل مكان آخر يقرأ منه لا يعدّل فيه.', 'Choose one place as the source, and every other place reads from it instead of editing it.'),
        c('إن كان النسخ اليدوي ضروريًا اليوم، فاجعل له وقتًا واحدًا محددًا، واكتب بجانب الرقم وقت آخر تحديث.', 'If manual copying is unavoidable today, give it one fixed time and write the last update time next to the number.'),
        c('أوقف البيع من القناة التي لا ترى الرقم، أو خصص لها كمية معروفة ومحدودة لا تُخلط بالباقي.', 'Stop selling from the channel that cannot see the number, or give it a known, limited quantity that is not mixed with the rest.'),
      ] },
      { p: c(
        'حل مؤقت نافع: خصص لكل قناة كمية صريحة. مثلًا تحفظ أربع قطع لجلسة بث أو لعرض في السوق، وتخرجها من المتاح العام قبل البدء. هذا ليس دقة كاملة، لكنه يمنع المفاجأة لأن القطع لم تُبَع مرتين.',
        'A useful temporary fix: allocate an explicit quantity per channel. For example, hold four pieces for a live session or market stall and remove them from general availability first. Not full accuracy, but it prevents the surprise because the pieces were not sold twice.',
      ) },

      { h: c('الخطوة 3: اخصم عند الاتفاق لا عند التسليم', 'Step 3: deduct at agreement, not at delivery') },
      { p: c(
        'اللحظة التي يقول فيها العميل "موافق" أو "أكيد" هي لحظة الحجز، لا لحظة الشحن. إن انتظرت حتى التسليم فقد يشتري القطعة عميل آخر في الوقت الفاصل، وأنت في الحالتين وعدت اثنين بشيء واحد. اخصم عند الاتفاق فورًا، حتى لو كان الدفع عند الاستلام.',
        'The moment the customer says "agreed" or "confirmed" is the moment to hold it, not the moment of shipping. If you wait until delivery another customer may buy that piece in between, and either way you promised two people one thing. Deduct at agreement right away, even if payment happens on delivery.',
      ) },
      { ol: [
        c('أكد الطلب بجملة مكتوبة: المنتج، الخيار، الكمية، السعر النهائي.', 'Confirm the order in one written line: product, option, quantity, final price.'),
        c('اخصم الكمية من الوحدة الصحيحة في السجل في نفس الدقيقة.', 'Deduct the quantity from the right unit in the record in the same minute.'),
        c('اكتب أن الطلب "محجوز" وليس "مُسلَّم"، فهما حالتان مختلفتان في المعنى.', 'Write that the order is "reserved", not "delivered", they mean different things.'),
        c('إن ألغى العميل، أعد الكمية بتسوية مسجلة بسبب واضح، لا بزيادة صامتة في الرقم.', 'If the customer cancels, return the quantity with a recorded adjustment and a clear reason, not a silent increase of the number.'),
        c('إن لم يؤكد بعد يومين، اسأله سؤالًا واحدًا قبل أن تُبقي الحجز.', 'If unconfirmed after two days, ask one question before keeping the hold.'),
      ] },
      { p: c(
        'حدّد مدة للحجز: يوم، يومان، أو حسب المنتج. الحجز المفتوح بلا مدة يجمّد بضاعة قد لا يشتريها أحد، فيبدو الصنف موجودًا وهو محتجز لعميل صامت. اكتب المدة، وأعد الكمية بعدها إن لم يصل رد.',
        'Set a hold duration: a day, two days, or depending on the item. An open ended hold freezes stock nobody may buy, so the item looks available while it is held for a silent customer. Write the duration and return the quantity after it if no reply arrives.',
      ) },

      { h: c('الخطوة 4: نقطة إعادة الطلب لكل صنف سريع', 'Step 4: a reorder point for each fast item') },
      { p: c(
        'نقطة إعادة الطلب هي الرقم الذي إن وصلت إليه الكمية تطلب من المورد، لا الرقم الذي تنتهي عنده. حسابها بسيط: كم تبيع في اليوم، مضروبًا في عدد الأيام التي يستغرقها المورد، ثم زد عليه هامشًا صغيرًا للأيام التي تبيع فيها أكثر من المعتاد.',
        'The reorder point is the number at which quantity triggers an order, not the number at which you run out. The calculation is simple: how much you sell per day, multiplied by the days the supplier takes, plus a small margin for days you sell more than usual.',
      ) },
      { p: c(
        'مثال افتراضي: صنف تبيع منه ثلاث قطع يوميًا، والمورد يستغرق أربعة أيام. تحتاج اثنتي عشرة قطعة لتغطية المدة، أي أن الطلب يبدأ عند هذا الرقم لا بعده، وإلا وصلت إلى الصفر قبل الشحنة. أضف هامشًا ليومين مضغوطين، فيصبح الرقم خمس عشرة أو ثماني عشرة قطعة.',
        'A hypothetical example: an item you sell three pieces of daily, and the supplier takes four days. You need twelve pieces to cover that period, so ordering starts at that number not after it, otherwise you reach zero before the shipment. Add a margin for two heavy days and it becomes fifteen or eighteen pieces.',
      ) },
      { p: c(
        'لا تحتاج هذا الحساب لكل صنف. ابدأ بالأصناف الأسرع حركة، وليكن عددها عشرة أو أقل، لأنها هي التي تسبب معظم الاعتذارات. الصنف البطيء لا يحتاج نقطة إعادة طلب، بل يحتاج قرارًا: هل تستمر في شرائه أصلًا؟',
        'You do not need this calculation for every item. Start with your fastest movers, ten or fewer, because they cause most of the apologies. A slow item does not need a reorder point, it needs a decision: should you keep buying it at all?',
      ) },
      { ul: [
        c('الصنف السريع: نقطة إعادة طلب مكتوبة، ومراجعة أسبوعية للرقم.', 'Fast item: a written reorder point and a weekly check of the number.'),
        c('الصنف المتوسط: مراجعة كل أسبوعين، وطلب عند اقتراب النفاد.', 'Medium item: a check every two weeks, and an order as it nears the end.'),
        c('الصنف البطيء: لا إعادة طلب، بل عرض لتصريفه قبل أن يتكدس.', 'Slow item: no reorder, but an offer to clear it before it piles up.'),
      ] },

      { h: c('الخطوة 5: سجّل ثلاث حركات فقط، وفي وقتها', 'Step 5: record only three movements, and on time') },
      { p: c(
        'كل ما يحدث للمخزون يدخل في ثلاثة أنواع: دخول من المورد، وخروج بالبيع، وتسوية بسبب. لا يوجد نوع رابع. إن التزمت بهذه الثلاثة يصبح الرقم صادقًا، وإن أهملت واحدة صار الرقم رأيًا لا حقيقة.',
        'Everything that happens to stock falls into three types: in from a supplier, out by sale, and an adjustment with a reason. There is no fourth type. If you keep to these three the number stays honest, and if you skip one it becomes an opinion rather than a fact.',
      ) },
      { ol: [
        c('دخول: سجّل الشحنة عند وصولها، لا عند دفع فاتورتها.', 'In: record the shipment when it arrives, not when its invoice is paid.'),
        c('خروج: كل بيع يخصم من وحدته المحددة، لا من سطر عام.', 'Out: every sale deducts from its specific unit, not from a general line.'),
        c('تسوية: تالف، مفقود، مرتجع، أو خطأ عد، مع سبب مكتوب في سطر.', 'Adjustment: damaged, lost, returned, or a counting error, with a written reason in one line.'),
        c('مراجعة: قارن الرقم بالعدّ الفعلي، ولا تصلح الفرق بصمت.', 'Review: compare the number with the physical count, and never fix a difference silently.'),
      ] },
      { p: c(
        'المرتجع يستحق انتباهًا خاصًا، لأن القطعة تعود إلى المخزون في حالتين مختلفتين: قطعة سليمة تُعاد كوحدة متاحة، وقطعة مستعملة أو تالفة لا تُعاد أصلًا. خلط الحالتين ينتهي ببيع قطعة لا تصلح، وهو أسوأ من الاعتذار عن النفاد.',
        'Returns deserve special attention, because a piece comes back to stock in two different states: a sound piece returns as an available unit, and a used or damaged piece does not return at all. Mixing the two ends with selling a piece that is not fit, which is worse than apologizing for a stockout.',
      ) },

      { h: c('قائمة تحقق يومية وأسبوعية', 'A daily and weekly checklist') },
      { p: c(
        'القوائم التالية قصيرة عن قصد. القائمة الطويلة لا تُنفَّذ، والقصيرة التي تُنفَّذ يوميًا أفضل من نظام كامل على الورق.',
        'The lists below are short on purpose. A long list does not get done, and a short one done daily beats a complete system on paper.',
      ) },
      { ul: [
        c('كل صباح: راجع الطلبات المفتوحة، وأعد الكميات المحجوزة التي انتهت مدتها.', 'Every morning: review open orders and return held quantities whose period expired.'),
        c('بعد كل بيع: اخصم فورًا من الوحدة الصحيحة، وسجّل اسم العميل مع الطلب.', 'After every sale: deduct immediately from the right unit and record the customer name with the order.'),
        c('كل مساء: تأكد أن عدد الطلبات المسجلة يساوي عدد الطلبات التي أُغلقت فعلًا.', 'Every evening: check that the number of recorded orders matches the orders actually closed.'),
        c('كل أسبوع: عدّ الأصناف الأسرع حركة باليد وقارن بالسجل.', 'Every week: physically count the fastest movers and compare with the record.'),
        c('كل أسبوع: راجع نقط إعادة الطلب، وعدّلها إن تغيرت سرعة البيع.', 'Every week: review reorder points and adjust them if the selling speed changed.'),
        c('كل شهر: جرد كامل، وقائمة بالأصناف التي لم تتحرك منذ شهر.', 'Every month: a full count, and a list of items that did not move for a month.'),
      ] },

      { h: c('أخطاء شائعة وكيف تصلحها', 'Common mistakes and how to fix them') },
      { ul: [
        c('الاعتماد على الذاكرة: اكتب الرقم في مكان واحد تراه قبل أن ترد على أي سؤال عن التوفر.', 'Relying on memory: write the number where you can see it before answering any availability question.'),
        c('بخس احتياطي مبالغ فيه: تخزين كمية كبيرة من كل صنف يجمّد رأس مالك. الاحتياطي للأصناف السريعة فقط.', 'An exaggerated safety stock: holding a lot of everything freezes your capital. Keep a buffer for fast items only.'),
        c('تعديل الرقم بأثر رجعي: "سأخصم آخر اليوم" يعني أن كل رد قبل آخر اليوم قد يكون خاطئًا.', 'Adjusting the number retroactively: "I will deduct at the end of the day" means every answer before then may be wrong.'),
        c('عدم تسجيل التالف: القطعة التي انكسرت ما زالت في السجل، فتظهر متاحة وتُباع.', 'Not recording damage: the piece that broke is still in the record, so it shows as available and gets sold.'),
        c('الحجز الشفهي: الوعد بلا كتابة يختفي بعد ساعتين، والقطعة تُباع لعميل آخر.', 'A verbal hold: a promise with no writing disappears in two hours, and the piece is sold to someone else.'),
        c('بيع الطقم دون خصم مكوناته: تظهر المكونات متاحة وأنت لا تستطيع تجميع طقم منها.', 'Selling a bundle without deducting its parts: the parts show as available while you cannot assemble a set from them.'),
        c('رقم واحد لكل الفروع: الخصم لا ينتقل، فتظن القطعة في الفرع الثاني وهي بيعت أمس.', 'One number for all branches: the deduction does not travel, so you think a piece is in the second branch when it sold yesterday.'),
        c('طلب المورد عند النفاد: الطلب عند الصفر يعني أيامًا بلا بيع لهذا الصنف.', 'Ordering from the supplier at zero: ordering at zero means days with no sales for that item.'),
      ] },

      { h: c('إذا حدث كذا فافعل كذا', 'If this happens, do this') },
      { ul: [
        c('إذا اكتشفت النفاد بعد أن وعدت عميلًا: أخبره في نفس اليوم قبل أن يدفع أو ينتظر. التأخير في الاعتذار أسوأ من النفاد.', 'If you discover a stockout after promising: tell the customer the same day, before payment or waiting. A late apology is worse than the stockout.'),
        c('إذا كان لديك نفس المنتج بلون أو مقاس آخر: اعرضه كخيار أول مع صورة، ودع القرار له.', 'If you have the same product in another color or size: offer it first with a photo, and leave the decision to them.'),
        c('إذا كان المنتج قادمًا من المورد: أعطه تاريخًا محددًا لا كلمة "قريبًا"، فالتاريخ يُبقي الطلب حيًا.', 'If the item is coming from the supplier: give a specific date, not "soon", a date keeps the order alive.'),
        c('إذا كان العميل قد دفع بالفعل: استرداد كامل أو بديل بموافقته، لا انتظار طويل بلا خيار.', 'If the customer already paid: a full refund or an alternative with their agreement, not a long wait with no options.'),
        c('إذا تكرر النفاد في صنف واحد مرتين: المشكلة في نقطة إعادة الطلب لا في الحظ. ارفع الرقم.', 'If the same item runs out twice: the problem is the reorder point, not luck. Raise the number.'),
        c('إذا كان الفرق بين السجل والعد كبيرًا ومتكررًا: ابحث عن سبب واحد، خطأ دخول، بيع غير مسجل، أو تالف لم يُكتب.', 'If the gap between record and count is large and repeated: find one cause, an entry error, an unrecorded sale, or unwritten damage.'),
        c('إذا كنت تبيع في البث المباشر: خصص كمية معروفة للبث واخرجها من المتاح العام قبل البدء.', 'If you sell on a live stream: allocate a known quantity and remove it from general availability first.'),
        c('إذا ألغى العميل بعد الحجز: أعد الكمية في نفس الدقيقة، فالرقم المجمّد يمنع بيعًا حقيقيًا.', 'If the customer cancels after a hold: return the quantity the same minute, a frozen number blocks a real sale.'),
      ] },

      { h: c('رسائل جاهزة للاعتذار عن النفاد', 'Ready messages for a stockout apology') },
      { p: c(
        'الاعتذار الجيد يحمل ثلاثة عناصر: اعتراف سريع بالوضع، وخياران على الأقل، وتاريخ إن كان هناك تاريخ. الاعتذار الذي لا يحمل خيارًا يترك العميل يبحث عن حل بنفسه، وغالبًا يجده عند متجر آخر.',
        'A good apology carries three elements: quick acknowledgement of the situation, at least two options, and a date if there is one. An apology with no option leaves the customer to find a solution alone, and they usually find it at another store.',
      ) },
      { ul: [
        c('اعتذار مع بديل: "المقاس الذي طلبته نفد فعلاً. لدي اللون نفسه بمقاس قريب، ولدي لون آخر بالمقاس نفسه. هل ترغب في أن أرسل الصور؟"', 'Apology with an alternative: "The size you asked for is actually gone. I have the same color in a close size, and another color in the same size. Want photos?"'),
        c('اعتذار مع موعد: "القطعة خلصت قبل طلبك بساعات. الشحنة الجديدة بتوصل يوم كذا، وأقدر أحجز لك واحدة منها بدون دفع. تحب؟"', 'Apology with a date: "The piece sold out hours before your order. The new shipment arrives on such a day, and I can hold one for you with no payment. Would you like that?"'),
        c('اعتذار مع استرداد: "للأسف لن يكتمل الطلب، وهذا خطأ مني. سأعيد إليك المبلغ كاملاً اليوم، وإن أردت بديلاً متوفراً أستطيع تجهيزه فوراً."', 'Apology with a refund: "Unfortunately the order cannot be completed, and that is my mistake. I am returning the full amount today, and if you want an available alternative I can prepare it right away."'),
        c('اعتذار بعد فوات وقت: "علمت متأخراً أن الصنف نفد، وأعتذر أنني لم أخبرك مبكراً. هذا خياري لك الآن، وإن لم يناسبك أعيد المبلغ فوراً."', 'Apology after a delay: "I learned late that the item was gone, and I am sorry I did not tell you earlier. Here are your options now, and if none fit I will refund immediately."'),
      ] },
      { p: c(
        'لاحظ أن كل رسالة تعطي خطوة تالية واضحة، وأن أيًا منها لا يعد بشيء لا تملكه. الوعد بتاريخ غير مؤكد هو الطريقة الأسرع لتحويل اعتذار واحد إلى شكوى.',
        'Notice that each message gives a clear next step, and none promises something you do not have. Promising an unconfirmed date is the fastest way to turn one apology into a complaint.',
      ) },

      { h: c('أين تساعدك أداة مثل FIHRIST؟', 'Where a tool like FIHRIST helps') },
      { p: c(
        'كل ما سبق قابل للتنفيذ بدفتر وجدول وقاعدة واحدة: اخصم عند الاتفاق. بهذه الطريقة ننصح بالبدء، وهي لا تحتاج أي نظام.',
        'Everything above can be done with a notebook, a sheet, and one rule: deduct at agreement. That is the way we recommend starting, and it needs no system.',
      ) },
      { p: c(
        'حين تكثر القنوات والطلبات يصبح الجمع اليدوي مرهقًا. في FIHRIST تُسجَّل المقاسات والألوان والخيارات كوحدات مخزون منفصلة، لكل منها سعرها وكميتها، وكل طلب يخصم الكمية المباعة من الخيار المحدد. الطلب مرتبط بالعميل والمنتج، ويمكن تعريف الصنف برمز QR، ومقارنة حركة الأصناف بين فترتين لمعرفة ما يتحرك بسرعة وما يتكدس. تعمل الواجهة بالعربية والإنجليزية.',
        'When channels and orders multiply, manual combining gets tiring. In FIHRIST, sizes, colors, and options are recorded as separate stock units, each with its own price and quantity, and every order deducts the quantity sold from the specific option. The order is linked to the customer and the product, an item can be identified with a QR code, and item movement can be compared across two periods to see what moves fast and what piles up. The interface works in Arabic and English.',
      ) },
      { p: c(
        'لا يوجد نظام يمنع كل خطأ بشري. من ينسى التسجيل سيخطئ في أي أداة، لكن توحيد الرقم في مكان واحد يزيل أكثر الأسباب شيوعًا، ويجعل الخطأ يظهر في نفس اليوم لا عند وصول العميل.',
        'No system prevents every human error. Someone who forgets to record will make mistakes in any tool, but keeping one number in one place removes the most common causes and makes the error appear the same day rather than when the customer arrives.',
      ) },
    ],
    faq: [
      {
        q: c('ما الفرق بين الكمية الموجودة والكمية المتاحة؟', 'What is the difference between quantity on hand and available quantity?'),
        a: c(
          'الموجودة هي كل ما تملكه فعليًا، بما فيه المحجوز. المتاحة هي الموجودة ناقص المحجوز ناقص التالف، وهي الرقم الذي تستطيع أن تعد به العميل. الفرق بينهما هو سبب معظم حالات البيع المزدوج، لأن البائع يقرأ الرقم الأول ويعده للعميل الثاني.',
          'On hand is everything you actually own, including what is reserved. Available is on hand minus reserved minus damaged, and it is the number you can promise a customer. The gap between the two causes most double selling, because the seller reads the first number and promises it to the second customer.',
        ),
      },
      {
        q: c('متى أخصم الكمية من المخزون، عند الطلب أم عند التسليم؟', 'When should I deduct stock, at order time or at delivery?'),
        a: c(
          'عند الاتفاق، أي في اللحظة التي يؤكد فيها العميل المنتج والخيار والكمية. الانتظار حتى التسليم يترك مجالًا لبيع القطعة لعميل آخر في الوقت الفاصل. اخصم عند التأكيد، واكتب أن الطلب محجوز، ثم أغلقه عند التسليم، وأعد الكمية بتسوية مسجلة إن ألغى العميل.',
          'At agreement, meaning the moment the customer confirms the product, option, and quantity. Waiting until delivery leaves room for another customer to buy the piece in between. Deduct at confirmation, record the order as reserved, close it at delivery, and return the quantity with a recorded adjustment if the customer cancels.',
        ),
      },
      {
        q: c('كيف أحسب نقطة إعادة الطلب لصنف سريع؟', 'How do I calculate a reorder point for a fast item?'),
        a: c(
          'اضرب متوسط ما تبيعه في اليوم في عدد الأيام التي يستغرقها المورد، ثم أضف هامشًا صغيرًا للأيام المزدحمة. إن كنت تبيع ثلاث قطع يوميًا ويستغرق المورد أربعة أيام، فأنت تحتاج اثنتي عشرة قطعة لتغطية المدة، والطلب يبدأ عند هذا الرقم أو قبله بقليل. راجع الرقم كل أسبوع، وعدّله إن تغيرت سرعة البيع.',
          'Multiply your average daily sales by the days your supplier takes, then add a small margin for busy days. If you sell three pieces a day and the supplier takes four days, you need twelve pieces to cover the period, and ordering starts at that number or slightly before it. Review the number weekly and adjust it if selling speed changes.',
        ),
      },
      {
        q: c('ماذا أقول لعميل طلب صنفًا نفد بعد أن وعدته؟', 'What do I say to a customer whose item sold out after I promised it?'),
        a: c(
          'قلها في نفس اليوم، وقدم خيارين على الأقل: مقاس أو لون قريب، أو حجز من الشحنة القادمة بتاريخ محدد، أو استرداد كامل. لا تقل "قريبًا" بلا تاريخ، ولا تترك الرسالة اعتذارًا فقط بلا خطوة تالية. الاعتراف السريع يحفظ الثقة أكثر من محاولة تغطية الخطأ.',
          'Say it the same day and offer at least two options: a close size or color, a hold from the next shipment with a specific date, or a full refund. Do not say "soon" without a date, and do not send an apology with no next step. Quick acknowledgement protects trust better than trying to cover the mistake.',
        ),
      },
      {
        q: c('هل أحتاج حدًّا أدنى لكل صنف في المتجر؟', 'Do I need a minimum level for every item in the store?'),
        a: c(
          'لا. ابدأ بالأصناف الأسرع حركة فقط، عشرة أو أقل، لأنها سبب معظم الاعتذارات. الصنف البطيء لا يفيده حد أدنى، بل يفيده قرار: هل تستمر في شرائه أم تعرضه لتصريفه؟ الحدود الكثيرة تصبح قائمة طويلة لا تُراجع، والقائمة التي لا تُراجع أسوأ من عدم وجودها لأنها تعطي إحساسًا زائفًا بالسيطرة.',
          'No. Start with your fastest movers only, ten or fewer, because they cause most of the apologies. A slow item is not helped by a minimum level but by a decision: keep buying it or clear it with an offer. Too many levels become a long list nobody reviews, and an unreviewed list is worse than none because it gives false confidence.',
        ),
      },
    ],
    related: ['inventory-tracking-for-small-stores', 'whatsapp-order-taking-checklist'],
    solution: 'inventory-management-system',
  },
};
