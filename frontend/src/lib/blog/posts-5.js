// Blog articles, expanded set 5. Same rules as posts-1.js and posts-2.js:
//   * Practical advice a store owner can use without FIHRIST.
//   * FIHRIST only in the final section, only with capabilities it really has.
//   * No invented statistics, studies, customers, prices or guarantees.
// Body blocks: { h: heading } | { p: paragraph } | { ul: [items] } | { ol: [items] }

const c = (ar, en) => ({ ar, en });

export const POSTS_5 = {
  'pos-for-small-shops-what-to-look-for': {
    date: '2026-11-15',
    minutes: 9,
    title: c('كيف تختار نظام كاشير لمحل صغير | FIHRIST', 'How to Choose a POS System for a Small Shop | FIHRIST'),
    description: c(
      'دليل شراء لنظام كاشير في محل صغير: قائمة تقييم، خطة تجربة أسبوع، أسئلة للبائع، علامات حمراء، وروتين إقفال اليوم.',
      'A buying guide for a small shop POS: an evaluation checklist, a one week trial plan, vendor questions, red flags, and a daily closing routine.',
    ),
    h1: c('كيف تختار نظام كاشير لمحل صغير', 'How to choose a POS system for a small shop'),
    lede: c(
      'الكاشير الجيد لا يسجل البيع فقط، بل يخبرك بما تبقى ومن اشترى. هذه المعايير تساعدك على المقارنة بين الخيارات دون أن تنجرف وراء قائمة مزايا طويلة، وتحميك من قرار تتعب منه بعد شهر.',
      'A good POS does more than record a sale: it tells you what is left and who bought. These criteria help you compare options without being swayed by a long feature list, and they protect you from a decision you regret a month later.',
    ),
    body: [
      { h: c('ابدأ من يومك العادي، لا من قائمة المزايا', 'Start from your normal day, not the feature list') },
      { p: c(
        'قبل أن تفتح أي عرض سعر، اجلس عشر دقائق واكتب ما يحدث في المحل فعلًا: من يفتح، من يبيع، كيف يُحدَّد السعر، كيف يُسجَّل البيع، كيف تعرف المتبقي، وماذا يحدث عندما يرجع عميل منتجًا. هذه الورقة أهم من أي مقارنة، لأن النظام الذي لا يطابق يومك سيُترك بعد أسبوع ويعود الجميع إلى الدفتر.',
        'Before you open any offer, sit for ten minutes and write down what actually happens in the shop: who opens, who sells, how the price is set, how the sale is recorded, how you know what is left, and what happens when a customer returns an item. This page matters more than any comparison, because a system that does not match your day gets abandoned within a week and everyone goes back to the notebook.',
      ) },
      { p: c(
        'أكثر ما يشتكي منه أصحاب المحلات ليس نقص المزايا، بل أن النظام يطلب منهم تغيير طريقة عملهم بالكامل. النظام الجيد يدخل في يومك كما هو ويحذف خطوات، لا يضيفها. عند كل شاشة اسأل: هل كانت هذه الخطوة موجودة قبل؟ إن كانت جديدة فما الذي توفره لي؟',
        'What shop owners complain about most is not missing features, it is a system that asks them to change how they work entirely. A good system fits into your day as it is and removes steps instead of adding them. At every screen ask: did this step exist before? If it is new, what does it save me?',
      ) },
      { h: c('قائمة تقييم سريعة قبل أي مقارنة', 'A quick evaluation checklist before any comparison') },
      { ul: [
        c('تسجيل البيع في خطوات قليلة: اختيار المنتج، الكمية، الدفع. كل خطوة زائدة تعني طابورًا وبيعًا قد يُلغى.', 'Recording a sale in few steps: pick the item, the quantity, the payment. Every extra step means a queue and a sale that may be dropped.'),
        c('خصم فوري من الوحدة الصحيحة، أي المقاس واللون والخيار، لأن رقمًا إجماليًا للصنف يخفي نفاد مقاس واحد.', 'An immediate deduction from the right unit, meaning size, color, and option, because one total per product hides that a single size ran out.'),
        c('الوصول للمنتج بالاسم أو الكود أو مسح رمز، حتى لا يعتمد البيع على حفظ الفريق لأسماء الأصناف.', 'Finding a product by name, code, or a scan, so selling does not depend on the team memorizing item names.'),
        c('ربط البيع بعميل، ولو برقم هاتف اختياري، لأن هذا هو ما يجعل المتابعة ممكنة لاحقًا.', 'Tying the sale to a customer, even with an optional phone number, because that is what makes follow-up possible later.'),
        c('صلاحيات واضحة: من يبيع، من يعدّل السعر، من يحذف، من يرى التقارير والتكلفة.', 'Clear permissions: who sells, who edits a price, who deletes, who sees reports and cost.'),
        c('خصومات ومرتجعات مسجلة بسببها، حتى تعرف كم تبيع فعلًا وكم يضيع في الخصم.', 'Discounts and returns recorded with a reason, so you know what you really sell and how much leaks through discounting.'),
        c('إقفال يوم يخرج بضغطة واحدة ويطابق النقد الموجود في الدرج.', 'A daily close that comes out in one action and matches the cash in the drawer.'),
        c('تصدير البيانات إلى ملف جدول، لأنك لا تريد أن تبقى أرقامك محبوسة داخل أداة.', 'Data export to a spreadsheet file, because you do not want your numbers trapped inside a tool.'),
        c('العمل أثناء انقطاع الإنترنت، أو على الأقل ألا يتوقف البيع تمامًا.', 'Working through an internet outage, or at least not stopping sales completely.'),
        c('واجهة عربية وإنجليزية سليمة يفهمها فريقك من أول يوم دون تدريب طويل.', 'A clean Arabic and English interface your team understands from day one without long training.'),
      ] },
      { h: c('سرعة تسجيل البيع: اختبرها بنفسك', 'Speed of recording a sale: test it yourself') },
      { p: c(
        'قف على الجهاز قبل الشراء وسجّل عشرة منتجات مختلفة: واحد بمقاس، وواحد بخصم، وواحد لعميل مسجل، وواحد مرتجع. احسب الوقت بنفسك. إن احتجت أكثر من دقيقة لعملية عادية، فالفريق سيتجاوز النظام عند الزحام، وهذا ليس ضعفًا فيهم بل نتيجة طبيعية لطابور ينتظر.',
        'Stand at the device before buying and record ten different items: one with a size, one with a discount, one for a registered customer, and one return. Time it yourself. If a normal sale takes more than a minute, the team will bypass the system when it gets busy, and that is not weakness on their part but the natural result of a queue waiting.',
      ) },
      { p: c(
        'السرعة ليست رفاهية. في وقت الزحام، كل ثانية إضافية تعني عميلًا يغادر أو خطأً في السعر. والأنظمة البطيئة لا تُكره الفريق على الصبر، بل تدفعه إلى الورق الذي يُنسى على الرف.',
        'Speed is not a luxury. At busy times, every extra second means a customer walking out or a wrong price. Slow systems do not force the team to be patient, they push them toward the paper that gets forgotten on the shelf.',
      ) },
      { h: c('ربط الكاشير بالمخزون: السؤال التقني الأهم', 'Linking the POS to stock: the most important technical question') },
      { p: c(
        'اسأل صراحة: هل البيع يخصم من الوحدة أم من الصنف؟ إن كان المنتج يأتي بثلاثة مقاسات ولونين، فأنت تبيع ست وحدات مختلفة، وخصم واحد من رقم إجمالي لا يخبرك أي مقاس نفد. وحين لا تعرف ذلك، تَعِد عميلًا بشيء غير موجود أو تطلب بضاعة موجودة بالفعل.',
        'Ask directly: does a sale deduct from the unit or from the product? If an item comes in three sizes and two colors, you are selling six different units, and a single deduction from one total never tells you which size ran out. When you do not know that, you promise a customer something you do not have or reorder something you already have.',
      ) },
      { p: c(
        'اسأل أيضًا عن الحالات الطرفية: ماذا يحدث إن باع شخصان آخر قطعة متاحة في نفس الدقيقة؟ وماذا لو رجع منتج، هل يعود للوحدة نفسها تلقائيًا أم يحتاج تسوية يدوية؟ وهل يمكنك إدخال بضاعة وصلت بسرعة دون المرور على كل شاشة؟ هذه الحالات هي التي تستهلك وقتك كل أسبوع.',
        'Also ask about edge cases: what happens if two people sell the last available piece in the same minute? What if an item comes back, does it return to the same unit automatically or need a manual adjustment? Can you enter arriving stock quickly without walking through every screen? These cases are what eat your time every week.',
      ) },
      { h: c('البيع والعميل في مكان واحد', 'The sale and the customer in one place') },
      { p: c(
        'كاشير لا يعرف من اشترى هو صندوق نقود دقيق فقط. عندما يظهر البيع في سجل العميل، تعرف من يشتري كل شهر ومن توقف، وتستطيع أن تعرض على من اشترى مقاسًا معينًا المتوفر منه الآن. هذا لا يحتاج تقنية معقدة، يحتاج أن يكون العميل جزءًا من البيع لا خانة تُترك فارغة دائمًا.',
        'A POS that does not know who bought is only an accurate cash box. When the sale appears on the customer record, you know who buys every month and who stopped, and you can offer someone who bought a certain size what is available in it now. This does not need complex technology, it needs the customer to be part of the sale rather than a field always left empty.',
      ) },
      { p: c(
        'إن لم يكن متجرك يسأل عن رقم العميل عند الدفع، ابدأ بسؤال اختياري واحد واشرح الفائدة بهدوء: أن يصله إشعار بالتوفر أو بالمقاس. من يرفض لا مشكلة، ومن يقبل يمنحك رابطًا حقيقيًا بين البيع والعميل.',
        'If your shop does not ask for a customer number at checkout, start with one optional question and explain the benefit calmly: being told when something is back or when a size arrives. Whoever declines is fine, and whoever accepts gives you a real link between the sale and the customer.',
      ) },
      { h: c('الصلاحيات: من يرى ماذا ومن يفعل ماذا', 'Permissions: who sees what and who does what') },
      { p: c(
        'اكتب ثلاثة أدوار قبل أن تختار نظامًا: بائع، مشرف، مالك. البائع يسجل ويطبع ويستعلم عن المخزون. المشرف يعدّل، ويقبل مرتجعًا، ويفتح وردية. المالك يرى التكلفة والتقارير ويغيّر الأسعار. ثم اسأل البائع: هل نظامك يسمح بهذا التقسيم؟ بعض الأنظمة تعطيك حسابًا واحدًا للجميع، وحينها أي موظف يستطيع حذف مبيعات اليوم كله دون أثر.',
        'Write three roles before you choose a system: seller, supervisor, owner. The seller records, prints, and checks stock. The supervisor edits, accepts a return, and opens a shift. The owner sees cost and reports and changes prices. Then ask the vendor: does your system allow this split? Some systems give you one account for everyone, and then any employee can delete the whole day of sales with no trace.',
      ) },
      { p: c(
        'الصلاحية الجيدة تحمي الموظف أيضًا، لا المالك فقط. عندما يكون الحذف والتعديل مسجلًا باسم صاحبه، لا يتهم أحد أحدًا بالخطأ، ويصبح النقاش عن السبب لا عن الشخص.',
        'Good permissions protect the employee too, not only the owner. When deletion and editing are recorded under the name of whoever did it, nobody accuses anyone of a mistake, and the discussion becomes about the cause instead of the person.',
      ) },
      { h: c('المرتجعات والخصومات: قواعد مكتوبة مسبقًا', 'Returns and discounts: rules written in advance') },
      { p: c(
        'القاعدة الأولى: كل مرتجع وكل خصم له سبب مسجل. ليس لمحاسبة الفريق، بل لتعرف أرقامك الحقيقية. لو كان جزء كبير من مبيعاتك يأتي بعد خصم، فأنت لا تبيع بالسعر الذي يظهر في أعلى التقرير، وقرارك التالي يجب أن يبني على السعر الفعلي.',
        'The first rule: every return and every discount gets a recorded reason. Not to hold the team accountable, but to know your real numbers. If a large part of your sales comes after a discount, you are not selling at the price shown at the top of the report, and your next decision must be built on the effective price.',
      ) },
      { p: c(
        'للمرتجع ثلاثة أسباب تتكرر: مقاس غير مناسب، وصف غير واضح، أو عيب في المنتج. كل سبب له حل مختلف. الأول يحتاج جدول مقاسات وصورًا تُظهر القياس، والثاني يحتاج وصفًا أدق وتوقعات واقعية، والثالث يحتاج مراجعة المورد نفسه. إن خلطت الأسباب في رقم واحد، ستعالج الاثنين الخطأ.',
        'Returns repeat for three reasons: a size that does not fit, an unclear description, or a defective item. Each cause needs a different fix. The first needs a size chart and photos that show the measurement, the second needs a more precise description and realistic expectations, and the third needs the supplier themselves reviewed. If you merge the reasons into one number, you will fix the wrong one.',
      ) },
      { p: c(
        'اطلب من النظام أن يطلب موافقة عند خصم يتجاوز حدًا تحدده، وأن يربط المرتجع بالطلب الأصلي لا أن ينشئ حركة سالبة بلا أصل. واكتب سياسة المرتجع في مكان يراه العميل قبل الشراء، فهذا يقلل النقاش عند الباب.',
        'Ask the system to require approval for a discount above a limit you set, and to link a return to its original order rather than creating a negative movement with no origin. Write your return policy where the customer sees it before buying, that reduces the argument at the door.',
      ) },
      { h: c('روتين إقفال اليوم في خمس دقائق', 'A five minute daily closing routine') },
      { p: c(
        'لا تكتفِ بجمع النقود وترك الدرج. الإقفال القصير كل يوم يمنع تراكم الأخطاء التي يصعب تفسيرها بعد شهر:',
        'Do not just collect the cash and leave the drawer. A short daily close prevents the pile up of errors that become impossible to explain a month later:',
      ) },
      { ol: [
        c('عدّ النقد الموجود فعلًا في الدرج، لا ما تتذكره.', 'Count the cash actually in the drawer, not what you remember.'),
        c('قارن مع مجموع المبيعات النقدية في النظام، وسجّل أي فرق ولو صغيرًا مع ملاحظة.', 'Compare with the cash sales total in the system and log any difference, however small, with a note.'),
        c('راجع المبيعات غير المكتملة أو المعلقة وأغلقها قبل أن تُنسى.', 'Review incomplete or pending sales and close them before they are forgotten.'),
        c('تحقق من المرتجعات المسجلة اليوم ومن سببها، لا من قيمتها فقط.', 'Check the returns recorded today and their reasons, not only their value.'),
        c('انظر إلى الأصناف التي وصلت إلى الحد الأدنى واترك طلب شراء أو ملاحظة.', 'Look at the items that hit their minimum level and leave a purchase note.'),
        c('اكتب سطرًا واحدًا: ما غير العادي اليوم؟ عرض، عطل، موظف غائب، صنف نفد.', 'Write one line: what was unusual today? A promotion, a fault, an absent employee, an item that ran out.'),
      ] },
      { h: c('عشرة أسئلة اسألها لأي بائع نظام', 'Ten questions to ask any system vendor') },
      { ul: [
        c('ماذا يحدث لبياناتي إن توقفت عن الدفع أو أغلقت الحساب؟ هل أستطيع أخذها كاملة؟', 'What happens to my data if I stop paying or close the account? Can I take all of it?'),
        c('هل أستطيع تصدير كل المبيعات والأصناف والعملاء إلى ملف جدول بضغطة واحدة؟', 'Can I export all sales, items, and customers to a spreadsheet in one action?'),
        c('كيف تُدار الأسعار: سعر واحد لكل صنف أم سعر مختلف لكل قناة أو لكل قائمة؟', 'How are prices managed: one price per item or a different price per channel or per list?'),
        c('هل يمكن تعديل بيع بعد إتمامه؟ من يملك الصلاحية؟ وهل يبقى أثر للتعديل؟', 'Can a completed sale be edited? Who is allowed? Is there a record of the edit?'),
        c('كيف يتعامل مع المقاسات والألوان والخيارات: وحدات منفصلة لكل منها سعر وكمية، أم رقم واحد للصنف؟', 'How does it handle sizes, colors, and options: separate units each with its own price and quantity, or one number per product?'),
        c('ماذا يحدث للمرتجع بعد أسبوع أو بعد شهر؟ وكيف يُربط بالطلب الأصلي؟', 'What happens to a return after a week or a month? How is it linked to the original order?'),
        c('هل يعمل على الجهاز الموجود عندي، وما متطلبات الإنترنت والطابعة؟', 'Does it run on the device I already have, and what are the internet and printer requirements?'),
        c('كيف يتم التدريب؟ وهل يوجد دعم بالعربية في ساعات عملي؟', 'How is training handled? Is there Arabic support during my working hours?'),
        c('أين تُخزَّن البيانات ومن يملكها، وما سياسة النسخ الاحتياطي؟', 'Where is the data stored, who owns it, and what is the backup policy?'),
        c('ما بنود الإلغاء والانتقال؟ وما الذي يُحتسب إضافيًا لاحقًا؟', 'What are the cancellation and migration terms? What is charged extra later?'),
      ] },
      { h: c('علامات حمراء توقف عندها', 'Red flags to stop at') },
      { ul: [
        c('عرض تجريبي لا يستطيع استيراد أصنافك، فتضطر لإدخال المتجر كله باليد قبل أن ترى فائدة.', 'A trial that cannot import your items, forcing you to enter the whole shop by hand before seeing any benefit.'),
        c('النظام يطلب منك تغيير طريقة عملك بالكامل، وليس العكس.', 'The system asks you to change how you work entirely, rather than the other way around.'),
        c('لا يوجد تصدير للبيانات، أو تصدير على شكل صورة فقط.', 'No data export, or an export that is only an image.'),
        c('لا صلاحيات، أو حساب واحد يستخدمه الجميع.', 'No permissions, or one account everyone shares.'),
        c('المخزون رقم إجمالي للصنف دون مقاسات وألوان.', 'Stock as one total per product with no sizes or colors.'),
        c('لا سجل لما تم تعديله أو حذفه، فلا تعرف من غيّر ماذا.', 'No record of what was edited or deleted, so you cannot tell who changed what.'),
        c('وعود مفتوحة بشيء تحتاجه اليوم: سنضيفه قريبًا. اطلب تاريخًا أو اعتبره غير موجود.', 'Open promises about something you need today: we will add it soon. Ask for a date or treat it as absent.'),
        c('فريق الدعم لا يتحدث لغة فريقك، فتصل المشكلة بعد أن يتعلم الموظفون تجاوز النظام.', 'Support does not speak your team language, so problems arrive after employees have learned to work around it.'),
      ] },
      { h: c('خطة تجربة أسبوع واحد', 'A one week trial plan') },
      { p: c(
        'التجربة الحقيقية ليست جلسة عرض أمام البائع، بل أسبوع من مبيعاتك. نفّذها بهذا الترتيب:',
        'A real trial is not a demo session in front of the vendor, it is a week of your own sales. Run it in this order:',
      ) },
      { ol: [
        c('اختر أسبوعًا عاديًا، لا أسبوع عرض كبير ولا أسبوع عطلة.', 'Choose a normal week, not a big promotion week and not a holiday week.'),
        c('أدخل الأصناف الأكثر بيعًا فقط، من عشرين إلى ثلاثين صنفًا، لا المتجر كله.', 'Load only your best selling items, twenty to thirty of them, not the whole shop.'),
        c('شغّل النظام بالتوازي مع طريقتك القديمة، وسجّل كل بيع في الاثنين.', 'Run the system in parallel with your old method and record every sale in both.'),
        c('في نهاية كل يوم قارن ثلاثة أرقام: إجمالي المبيعات، عدد الطلبات، والأصناف المنفذة.', 'At the end of each day compare three numbers: total sales, order count, and items that ran out.'),
        c('اسأل الشخص الذي وقف على الجهاز فعلًا، لا من باع لك النظام.', 'Ask the person who actually stood at the device, not the one who sold you the system.'),
        c('في اليوم السابع اكتب ثلاث نقاط: ما وفّره، وما أبطأك، وما ينقصك.', 'On day seven write three points: what it saved, what slowed you down, what is missing.'),
        c('قرر بوضوح: تتبنى، تمدد التجربة أسبوعًا آخر، أو تترك. لا توقّع التزامًا طويلًا قبل هذه الخطوة.', 'Decide clearly: adopt it, extend the trial a week, or leave it. Do not sign a long commitment before this step.'),
      ] },
      { p: c(
        'إن كان الفريق يتهرب من الجهاز في الأسبوع الأول، فالمشكلة غالبًا في السرعة أو في التدريب، لا في الفريق. اكتب ما يقوله لك حرفيًا، فهو أصدق تقرير ستقرأه عن النظام.',
        'If the team avoids the device in the first week, the problem is usually speed or training, not the team. Write down what they tell you word for word, it is the most honest review of the system you will read.',
      ) },
      { h: c('أين يقف FIHRIST من هذه القائمة', 'Where FIHRIST stands against this list') },
      { p: c(
        'يعمل كاشير FIHRIST من المتصفح على المنتجات والمخزون نفسهما، فيُخصم المبيع من الوحدة المحددة ويظهر البيع في سجل العميل. لكل مقاس أو لون أو خيار وحدة مستقلة بسعرها وكميتها، ويمكن استخدام رمز QR لتعريف الصنف، وربط الطلب بالمحادثة التي بدأ منها، ومقارنة حركة الأصناف بين فترات. تُضبط الصلاحيات لكل عضو، وواجهة العمل بالعربية والإنجليزية. للأجهزة المناسبة أو لتعدد الفروع تواصل معنا. ابدأ بقائمة التقييم وخطة الأسبوع أعلاه، فهي تنفع مع أي نظام تختاره.',
        'The POS in FIHRIST runs in the browser on the same products and stock, so a sale deducts from the specific unit and shows on the customer record. Each size, color, or option is its own unit with its own price and quantity, a QR code can be used to identify an item, an order can be linked to the conversation it started from, and item movement can be compared across periods. Permissions are set per member, and the interface works in Arabic and English. Contact us about suitable devices or multiple branches. Start with the checklist and the one week plan above, they work with any system you choose.',
      ) },
    ],
    related: ['inventory-tracking-for-small-stores', 'prevent-overselling-and-stockouts'],
    solution: 'pos-cashier-system',
    faq: [
      { q: c('هل أحتاج نظام كاشير لمحل صغير جدًا؟', 'Does a very small shop need a POS system?'),
        a: c(
          'لا تحتاج نظامًا لمجرد أنك تبيع، لكنك تحتاجه عندما تصبح الأرقام أكثر من قدرتك على تذكرها: أصناف بمقاسات مختلفة، بيع على أكثر من قناة، وموظف أو اثنان. إن كنت تبيع عشر قطع يوميًا وتذكر ما تبقى، فالدفتر يكفي الآن. المشكلة تبدأ حين تعِد عميلًا بشيء نفد، أو حين تكتشف بعد أسبوع أن الربح لم يكن كما ظننت. القرار مرتبط بحجم العمل لا بحجم المحل.',
          'You do not need a system just because you sell, you need one when the numbers exceed what you can remember: items with several sizes, sales over more than one channel, and one or two employees. If you sell ten pieces a day and know what is left, a notebook is enough for now. The trouble starts when you promise a customer something that ran out, or discover a week later that profit was not what you assumed. The decision depends on the volume of work, not the size of the shop.',
        ) },
      { q: c('ما الفرق بين الكاشير ونظام إدارة المخزون؟', 'What is the difference between a POS and an inventory system?'),
        a: c(
          'الكاشير هو نقطة البيع: الشاشة التي يسجل عليها البيع ويُطبع الإيصال وتُحصّل النقود. نظام المخزون يتابع الكميات والوحدات والحد الأدنى وتاريخ الحركة. عندما يكونان منفصلين، تسجل البيع في مكان وتخصم في مكان آخر باليد، وهذا مصدر معظم الأرقام المتضاربة في المتاجر الصغيرة. الأفضل أن يكون البيع والمخزون على نفس البيانات، وإلا فستقضي وقتًا في المطابقة كل أسبوع.',
          'The POS is the point of sale: the screen where the sale is recorded, the receipt printed, and the money collected. An inventory system tracks quantities, units, minimum levels, and movement history. When they are separate, you record the sale in one place and deduct in another by hand, which is the source of most conflicting numbers in small shops. It is better for sales and stock to sit on the same data, otherwise you spend time reconciling every week.',
        ) },
      { q: c('هل يمكن تشغيل الكاشير على موبايل أو لابتوب عادي؟', 'Can a POS run on a phone or an ordinary laptop?'),
        a: c(
          'كثير من الأنظمة الحديثة تعمل من المتصفح، أي من لابتوب أو تابلت أو موبايل، دون تثبيت برنامج ثقيل. اسأل قبل الشراء عن ثلاثة أشياء: هل يحتاج إنترنت دائمًا، هل يعمل مع الطابعة التي عندك، وهل الشاشة الصغيرة تكفي لعرض الأصناف بسرعة. جرّب على جهازك أنت، لا على جهاز العرض في المعرض، لأن السرعة على جهازك هي ما سيحدد إن كان الفريق سيستخدمه.',
          'Many modern systems run in a browser, meaning from a laptop, tablet, or phone, without installing heavy software. Before buying, ask three things: does it need a permanent internet connection, does it work with the printer you have, and is a small screen enough to browse items quickly. Test on your own device, not the demo device, because speed on your device is what decides whether the team will use it.',
        ) },
      { q: c('كيف أوازن بين تكلفة النظام والدفتر؟', 'How do I weigh the cost of a system against a notebook?'),
        a: c(
          'لا تقارن سعر الاشتراك بسعر الدفتر، بل بما يضيع عليك اليوم: بيع ملغى بسبب طابور، صنف نفد ولم تلاحظ، خصم منحته ولم تسجله، وعميل قديم لم يعد. اكتب ثلاثة أرقام تقديرية من واقع أسبوعك، ثم قرر إن كان النظام يعالج واحدًا منها على الأقل. اطلب دائمًا توضيح ما يُحتسب إضافيًا لاحقًا، وابدأ بأصغر باقة تكفي عملك الحالي.',
          'Do not compare the subscription price with the price of a notebook, compare it with what you lose today: a sale dropped because of a queue, an item that ran out unnoticed, a discount given and never recorded, an old customer who did not come back. Write three estimated numbers from your own week, then decide whether the system fixes at least one of them. Always ask what is charged extra later, and start with the smallest plan that covers your current work.',
        ) },
      { q: c('ماذا أفعل إن انقطع الإنترنت أثناء البيع؟', 'What do I do if the internet drops during selling?'),
        a: c(
          'اسأل عن هذا قبل الشراء واكتب الجواب. بعض الأنظمة تكمل العمل محليًا وتزامن عند العودة، وبعضها يتوقف. إن كان نظامك يحتاج إنترنت، فاحتفظ بورقة بسيطة للطوارئ: الصنف، الكمية، السعر، والوقت، ثم أدخلها عند العودة وسجّلها كتسوية حتى يبقى المخزون صحيحًا. الأهم ألا يبدأ الفريق في البيع دون تسجيل، لأن الفرق سيظهر بعد أيام بصعوبة.',
          'Ask about this before buying and write the answer down. Some systems keep working locally and sync when the connection returns, others stop. If your system needs internet, keep a simple paper fallback: item, quantity, price, time, then enter those when you are back and record them as adjustments so stock stays correct. What matters most is that the team does not start selling without recording, because that gap shows up days later and is hard to trace.',
        ) },
    ],
  },

  'sales-report-basics-for-store-owners': {
    date: '2026-11-15',
    minutes: 8,
    title: c('أساسيات قراءة تقرير المبيعات لصاحب المتجر | FIHRIST', 'Sales Report Basics for Store Owners | FIHRIST'),
    description: c(
      'كيف تقرأ تقرير مبيعاتك: المقاييس الأساسية بصيغ حسابها، روتين أسبوعي، مثال بأرقام افتراضية، وفخاخ المقارنة.',
      'How to read your sales report: the basic metrics with their formulas, a weekly routine, a worked example with hypothetical numbers, and comparison traps.',
    ),
    h1: c('أساسيات قراءة تقرير المبيعات', 'Sales report basics for store owners'),
    lede: c(
      'التقرير ليس هدفًا بل أداة لقرار. هذه أسئلة بسيطة تحوّل الأرقام إلى خطوة تفعلها هذا الأسبوع، وتحميك من استنتاج سريع يكلفك شهرًا.',
      'A report is not a goal, it is a tool for a decision. These simple questions turn numbers into something you do this week, and protect you from a quick conclusion that costs you a month.',
    ),
    body: [
      { h: c('التقرير يجيب عن ثلاثة أسئلة فقط', 'A report answers only three questions') },
      { p: c(
        'أكثر ما يُتعب صاحب المتجر هو فتح تقرير فيه عشرون رقمًا ولا يعرف من أين يبدأ. اختصر على نفسك: ما الذي باع؟ ما الذي لم يبِع؟ وهل الأرقام أفضل أم أسوأ من فترة مشابهة؟ كل ما بعد ذلك تفصيل يخدم هذه الأسئلة الثلاثة، وما لا يخدمها يمكن تجاهله هذا الأسبوع.',
        'What tires a store owner most is opening a report with twenty numbers and not knowing where to start. Simplify: what sold? What did not sell? And are the numbers better or worse than a similar period? Everything after that is detail serving these three questions, and whatever does not serve them can be ignored this week.',
      ) },
      { p: c(
        'الخطأ الشائع أن يُقرأ الرقم الأعلى في الصفحة كأنه حكم. إجمالي المبيعات قد يرتفع بينما الربح ينخفض، وقد ينخفض بينما المتجر في حال أفضل. لهذا تحتاج رقمين أو ثلاثة معًا، لا رقمًا واحدًا، قبل أن تحكم.',
        'The common mistake is reading the biggest number on the page as a verdict. Total sales can rise while profit falls, and can fall while the shop is in better shape. That is why you need two or three numbers together, not one, before judging.',
      ) },
      { h: c('المقاييس التي يكفيها متجر صغير وصيغة كل واحد', 'The metrics a small store actually needs, and how each is calculated') },
      { p: c(
        'لا تحتاج عشرين مؤشرًا. هذه المجموعة تكفي لاتخاذ قرار أسبوعي، وكل واحد منها يمكن حسابه من تصدير بسيط أو بجمع يدوي في نهاية اليوم:',
        'You do not need twenty indicators. This set is enough for a weekly decision, and each one can be calculated from a simple export or by hand at the end of the day:',
      ) },
      { ul: [
        c('عدد الطلبات: عدّ الطلبات المؤكدة فقط، لا المحادثات. المحادثة لا تصبح طلبًا حتى يُتفق على منتج وسعر وطريقة تسليم.', 'Order count: count confirmed orders only, not conversations. A chat is not an order until a product, a price, and a delivery method are agreed.'),
        c('إجمالي المبيعات: مجموع قيمة الطلبات بعد الخصم. إن كنت تفصل الشحن فاحسبه خارج الرقم أو أظهره منفصلًا، حتى لا يبدو الإيراد أكبر مما هو.', 'Total sales: the sum of order values after discount. If you separate shipping, keep it outside the figure or show it separately, so revenue does not look bigger than it is.'),
        c('متوسط قيمة الطلب = إجمالي المبيعات ÷ عدد الطلبات. يخبرك إن كان العميل يشتري أكثر أم أقل في كل زيارة.', 'Average order value = total sales divided by number of orders. It tells you whether a customer is buying more or less per visit.'),
        c('عدد الوحدات في الطلب = الوحدات المباعة ÷ عدد الطلبات. مفيد إن كنت تبيع قطعًا صغيرة، لأنه يكشف البيع المتعدد الذي يخفيه متوسط السعر.', 'Units per order = units sold divided by number of orders. Useful if you sell small pieces, because it reveals multi item buying that an average price hides.'),
        c('معدل التحويل = عدد الطلبات ÷ عدد المحادثات الجديدة × 100. يقيس قدرة المحادثة على الوصول إلى قرار، لا حجم الرسائل.', 'Conversion rate = orders divided by new conversations, multiplied by 100. It measures how well a conversation reaches a decision, not message volume.'),
        c('هامش الربح الإجمالي للصنف = (سعر البيع ناقص تكلفة الشراء) ÷ سعر البيع × 100. احسبه لكل صنف، ثم انظر إلى وزن الأصناف في المبيعات، لأن الصنف الأكثر بيعًا قد لا يكون الأكثر ربحًا.', 'Gross margin per item = (selling price minus purchase cost) divided by selling price, multiplied by 100. Calculate it per item, then look at each item weight in sales, because the best seller may not be the most profitable.'),
        c('نسبة المرتجعات = الطلبات المرتجعة ÷ الطلبات المسلَّمة × 100. اقسم على المسلَّم لا على المؤكد، لأن الطلب الذي لم يصل بعد لا يمكن أن يُرتجع.', 'Return rate = returned orders divided by delivered orders, multiplied by 100. Divide by delivered, not confirmed, because an order that has not arrived cannot be returned.'),
        c('معدل دوران الصنف = الوحدات المباعة في الفترة ÷ متوسط الوحدات الموجودة في المخزون خلال الفترة. الرقم الأعلى يعني بضاعة تتحرك، والأقل يعني رأس مال نائم على الرف.', 'Item turnover = units sold in the period divided by the average units held in stock during the period. A higher figure means stock is moving, a lower one means capital sitting on the shelf.'),
        c('المبيعات اليومية المتوسطة = مبيعات الفترة ÷ عدد أيام البيع الفعلية، لا عدد أيام الأسبوع. هذا الرقم وحده ينقذك من مقارنات غير عادلة.', 'Average daily sales = period sales divided by actual selling days, not the number of days in the week. This single figure saves you from unfair comparisons.'),
      ] },
      { h: c('روتين مراجعة أسبوعي في نصف ساعة', 'A weekly review routine in half an hour') },
      { p: c(
        'المراجعة التي تحدث كل يوم تُقرأ ولا تُنفَّذ. حدد موعدًا ثابتًا، مرة واحدة في الأسبوع، ويفضل نفس اليوم ونفس الساعة، واتبع الترتيب نفسه في كل مرة حتى لا تنسى بندًا:',
        'A review that happens every day gets read and not acted on. Set a fixed appointment, once a week, ideally the same day and hour, and follow the same order each time so you do not skip a step:',
      ) },
      { ol: [
        c('اكتب الأرقام التسعة أعلاه في ورقة واحدة أو ملف واحد، بنفس الترتيب كل أسبوع.', 'Write the nine figures above into one sheet or file, in the same order every week.'),
        c('قارن بالأسبوع السابق، ثم بالأسبوع نفسه من الشهر الماضي إن توفر.', 'Compare with last week, then with the same week last month if you have it.'),
        c('اكتب أعلى خمسة أصناف وأدنى خمسة في الحركة، وأضف سببًا إن كنت تعرفه.', 'List the top five and bottom five items by movement, and add a reason if you know one.'),
        c('راجع الأصناف التي نفدت أو وصلت إلى الحد الأدنى، لأنها تفسر جزءًا من أي انخفاض.', 'Review items that ran out or hit their minimum, they explain part of any drop.'),
        c('راجع المرتجعات بأسبابها، والمحادثات التي لم يُرد عليها.', 'Review returns with their reasons, and conversations that went unanswered.'),
        c('اختر قرارًا واحدًا للأسبوع القادم واكتبه بصيغة قابلة للقياس: ماذا ستفعل، وعلى أي صنف.', 'Choose one decision for next week and write it in measurable terms: what you will do, and on which item.'),
        c('اكتب سطرًا للظروف: عرض، عطلة، توقف مورد، عطل. بعد شهر سيكون هذا السطر هو الفرق بين تفسير وتخمين.', 'Write one line about circumstances: a promotion, a holiday, a supplier pause, a fault. A month later this line is the difference between an explanation and a guess.'),
      ] },
      { h: c('مثال عملي: قراءة أسبوعين متتاليين', 'A worked example: reading two consecutive weeks') },
      { p: c(
        'الأرقام التالية افتراضية بالكامل، لغرض التوضيح فقط، والوحدة النقدية غير محددة لأن ما يهم هو العلاقة بين الأرقام لا حجمها. ونفترض أن كل الطلبات سُلِّمت في الأسبوعين، حتى تُحسب نسبة المرتجعات على أساس واحد.',
        'The figures below are entirely hypothetical, for illustration only, and the currency unit is unspecified because what matters is the relation between the numbers, not their size. We also assume every order was delivered in both weeks, so the return rate is calculated on one basis.',
      ) },
      { ul: [
        c('الأسبوع الأول: 200 محادثة جديدة، 40 طلبًا، مبيعات 12,000، 56 وحدة مباعة، 4 مرتجعات.', 'Week one: 200 new conversations, 40 orders, sales of 12,000, 56 units sold, 4 returns.'),
        c('الأسبوع الثاني: 260 محادثة جديدة، 44 طلبًا، مبيعات 12,100، 66 وحدة مباعة، 3 مرتجعات.', 'Week two: 260 new conversations, 44 orders, sales of 12,100, 66 units sold, 3 returns.'),
      ] },
      { p: c(
        'بالنظر السريع، المبيعات شبه ثابتة: من 12,000 إلى 12,100. لكن الحساب يقول شيئًا آخر. متوسط قيمة الطلب نزل من 300 (12,000 ÷ 40) إلى 275 (12,100 ÷ 44). وعدد الوحدات في الطلب ارتفع من 1.4 (56 ÷ 40) إلى 1.5 (66 ÷ 44). ومعدل التحويل نزل من 20 في المئة (40 ÷ 200) إلى نحو 17 في المئة (44 ÷ 260). ونسبة المرتجعات تحسنت من 10 في المئة إلى نحو 7 في المئة.',
        'On a quick look, sales are almost flat: from 12,000 to 12,100. But the arithmetic says something else. Average order value fell from 300 (12,000 divided by 40) to 275 (12,100 divided by 44). Units per order rose from 1.4 (56 divided by 40) to 1.5 (66 divided by 44). Conversion fell from 20 percent (40 divided by 200) to about 17 percent (44 divided by 260). The return rate improved from 10 percent to about 7 percent.',
      ) },
      { p: c(
        'القراءة الأصدق: المتجر لم ينمُ، بل تغيّر شكله. العميل صار يشتري قطعًا أكثر لكن أرخص، والدليل أن متوسط سعر الوحدة نزل من نحو 214 (12,000 ÷ 56) إلى نحو 183 (12,100 ÷ 66). وفي الوقت نفسه احتجت محادثات أكثر للحصول على كل طلب. هذا يفتح احتمالين لا ثالث لهما حتى تتحقق: إما أن صنفًا رخيصًا حرّك الكمية هذا الأسبوع، وإما أن الخصومات زادت. الفرق بينهما كبير: الأول مزيج بيع، والثاني ربح أقل بنفس الإيراد.',
        'The honest reading: the shop did not grow, it changed shape. Customers bought more pieces but cheaper ones, and the proof is that average unit price fell from about 214 (12,000 divided by 56) to about 183 (12,100 divided by 66). At the same time you needed more conversations to get each order. That leaves two possibilities until you check: either a cheap item drove the volume this week, or discounts increased. The difference matters: the first is a product mix shift, the second is less profit on the same revenue.',
      ) },
      { p: c(
        'كيف تحسم؟ افتح حركة الأصناف في الأسبوع الثاني وانظر من أضاف الوحدات العشر الزائدة. إن كانت الإضافة كلها من صنف واحد رخيص، فالمزيج هو السبب. وإن كانت الزيادة موزعة مع نسبة خصم أعلى، فالخصم هو السبب. وفي الحالتين، اكتب ما وجدته بجانب الرقم، لأن الأسبوع القادم سيُقارن بهذا الأسبوع.',
        'How do you settle it? Open item movement for week two and see which item added the extra ten units. If the whole addition came from one cheap item, mix is the cause. If the increase is spread out with a higher discount share, discounting is the cause. In both cases write what you found next to the number, because next week will be compared with this one.',
      ) },
      { h: c('فخاخ المقارنة: متى يكون الرقمان غير قابلين للمقارنة', 'Comparison traps: when two numbers cannot be compared') },
      { p: c(
        'أغلب الاستنتاجات الخاطئة لا تأتي من سوء النية، بل من مقارنة رقمين لا يقيسان الشيء نفسه. هذه أكثر الفخاخ شيوعًا في متجر صغير:',
        'Most wrong conclusions do not come from bad intent, they come from comparing two numbers that do not measure the same thing. These are the most common traps in a small shop:',
      ) },
      { ul: [
        c('عدد الأيام: أسبوع فيه عطلة أو يوم إغلاق لا يُقارن بأسبوع كامل. استخدم المبيعات اليومية المتوسطة بدل الإجمالي.', 'Number of days: a week with a holiday or a closed day cannot be compared with a full week. Use average daily sales instead of the total.'),
        c('الموسم: آخر أسبوع قبل عيد أو في رمضان ليس مثل أسبوع عادي. قارن بالشهر نفسه من العام الماضي إن توفر، أو اقبل أن المقارنة ضعيفة واكتب ذلك.', 'Season: the last week before a holiday or during Ramadan is not a normal week. Compare with the same month last year if you have it, or accept that the comparison is weak and write that down.'),
        c('نفاد المخزون: إن نفد صنف سريع الحركة ثلاثة أيام، فانخفاض رقمه ليس ضعف طلب بل غياب عرض. استثنِ الأيام التي كان فيها ناقصًا.', 'Stockouts: if a fast mover was out for three days, its lower figure is not weaker demand but absent supply. Exclude the days it was missing.'),
        c('تغيير السعر أو الخصم: مبيعات أعلى بعد خصم كبير قد تعني ربحًا أقل. قارن الإيراد والهامش معًا، لا الإيراد وحده.', 'A price or discount change: higher sales after a big discount may mean lower profit. Compare revenue and margin together, not revenue alone.'),
        c('طلب واحد كبير: عميل اشترى كمية لمرة واحدة يشوه المتوسط. اذكر الطلبات غير العادية في هامش التقرير بدل أن تدعها تصنع قاعدة.', 'One large order: a customer buying a batch once distorts the average. Note unusual orders in the margin of the report instead of letting them create a rule.'),
        c('تغيير طريقة القياس: إن بدأت تسجل المحادثات هذا الأسبوع فقط، فمعدل التحويل غير قابل للمقارنة بأي أسبوع سابق. ابدأ القياس واعتبر أول أسبوع خط أساس.', 'A change in how you measure: if you only started recording conversations this week, conversion cannot be compared with any earlier week. Start measuring and treat the first week as a baseline.'),
        c('تغيّر القناة: انتقال محادثات من واتساب إلى إنستغرام لا يعني أن واتساب تراجع، بل أن الناس غيّروا المكان. انظر إلى الإجمالي قبل أن تحكم على قناة.', 'A channel shift: conversations moving from WhatsApp to Instagram does not mean WhatsApp declined, it means people changed place. Look at the total before judging a channel.'),
      ] },
      { h: c('متى يكون الرقم المرتفع خبرًا سيئًا', 'When a higher number is bad news') },
      { p: c(
        'ليس كل صعود نجاحًا. أربع حالات يستحق فيها الرقم المرتفع مراجعة قبل الاحتفال: ارتفاع المبيعات مع ارتفاع المرتجعات، لأنك تبيع ما يعود؛ ارتفاع المبيعات مع انخفاض الهامش، لأنك تشتري حجمًا بثمن ربحي؛ ارتفاع عدد الطلبات مع انخفاض متوسط قيمتها بشدة، لأنك تحصل على مجهود أكبر بنفس الإيراد؛ وارتفاع المحادثات مع ثبات الطلبات، لأنك تدفع ثمنًا في وقت الرد دون نتيجة.',
        'Not every rise is a success. Four cases deserve a review before celebrating: sales up with returns up, because you are selling what comes back; sales up with margin down, because you are buying volume at the cost of profit; order count up with average value falling sharply, because you get more effort for the same revenue; and conversations up with orders flat, because you pay in reply time with no result.',
      ) },
      { h: c('من الملاحظة إلى قرار: إن حدث كذا فافعل كذا', 'From observation to decision: if this, then that') },
      { ul: [
        c('إن ارتفعت المبيعات ونزل متوسط قيمة الطلب: راجع نسبة الخصم ومزيج الأصناف قبل أن تعتبر الشهر ناجحًا.', 'If sales rose and average order value fell: check the discount share and the item mix before calling the month a success.'),
        c('إن ارتفعت المحادثات ونزل معدل التحويل: راجع سرعة الرد وأكثر سؤال متكرر، فقد يكون سؤال واحد يمنع القرار.', 'If conversations rose and conversion fell: check reply speed and the most repeated question, one question may be blocking the decision.'),
        c('إن نزلت المبيعات ونزلت المرتجعات معها: قد يكون التراجع بسبب تشكيلة أضيق لا بسبب ضعف الطلب.', 'If sales fell and returns fell with them: the drop may come from a narrower assortment rather than weaker demand.'),
        c('إن نزلت مبيعات صنف بعينه وصعدت مبيعات بديل له: هذه حركة تحويل داخل المتجر، لا خسارة.', 'If one item fell while a substitute rose: that is a shift inside the shop, not a loss.'),
        c('إن تكرر صنف في المرتجعات: راجع الوصف والمقاسات والصور قبل أن توقف شراءه.', 'If one item keeps appearing in returns: check the description, sizes, and photos before you stop buying it.'),
        c('إن وصل صنف سريع الحركة إلى الحد الأدنى مرتين في شهر: ارفع الحد الأدنى أو قصّر مدة التوريد.', 'If a fast mover hits its minimum twice in a month: raise the minimum level or shorten the supply lead time.'),
        c('إن كان صنف يباع ببطء وهامشه مرتفع: لا توقفه فورًا، جرّب عرضه على من اشترى شيئًا قريبًا منه.', 'If an item sells slowly but has a high margin: do not drop it immediately, try offering it to whoever bought something close to it.'),
        c('إن كان صنف يباع بسرعة وهامشه ضعيف: راجع سعر الشراء أو ارفع السعر قليلًا وقس الأثر أسبوعًا.', 'If an item sells fast with a thin margin: revisit the purchase cost or raise the price slightly and measure the effect for a week.'),
        c('إن تكرر الفرق بين النقد في الدرج والتقرير: راجع روتين الإقفال والصلاحيات قبل أن تشك في شخص.', 'If the gap between drawer cash and the report repeats: review the closing routine and permissions before suspecting a person.'),
      ] },
      { h: c('أخطاء شائعة في قراءة التقارير', 'Common mistakes in reading reports') },
      { ul: [
        c('تغيير عدة أشياء في أسبوع واحد ثم محاولة معرفة أيها نجح. غيّر شيئًا واحدًا واقرأ أثره.', 'Changing several things in one week then trying to find out which one worked. Change one thing and read its effect.'),
        c('الحكم من يوم واحد. يوم واحد قد يكون عطلة أو عطلًا أو مزاجًا، والأسبوع هو أصغر وحدة تُقرأ.', 'Judging from a single day. One day may be a holiday, a fault, or a mood, and a week is the smallest unit worth reading.'),
        c('مقارنة هذا الشهر بالشهر الماضي دون النظر إلى عدد الأيام أو العطلات.', 'Comparing this month with last month without looking at day count or holidays.'),
        c('قراءة الإيراد فقط وإهمال الهامش، فتظن أنك ربحت وأنت تدور في مكانك.', 'Reading revenue only and ignoring margin, so you believe you profited while standing still.'),
        c('عدم كتابة ما حدث. بعد ثلاثة أسابيع لن تتذكر أن المورد تأخر أو أن المنتج نفد، وستفسر الرقم تفسيرًا خاطئًا.', 'Not writing down what happened. Three weeks later you will not remember the supplier delay or the stockout, and you will explain the number wrongly.'),
        c('استخدام التقرير للحكم على الفريق بدل تحسين العمل. الأرقام تدل على خطوة تحتاج تعديلًا، لا على شخص يستحق اللوم.', 'Using the report to judge the team instead of improving the work. Numbers point at a step that needs adjusting, not a person to blame.'),
      ] },
      { h: c('ما تكتبه كل أسبوع حتى تصبح المقارنة ممكنة', 'What to write each week so comparison becomes possible') },
      { p: c(
        'أهم ما في التقرير ليس ما يعرضه اليوم، بل ما تحتفظ به للمقارنة غدًا. احتفظ بصفحة واحدة لكل أسبوع فيها الأرقام التسعة، وأعلى الأصناف وأدنى الأصناف، وسبب واحد لكل حركة غير عادية، وقرار واحد اتخذته. بعد شهرين ستصبح هذه الصفحات سلسلة، وهي أثمن من أي تقرير جاهز لأنها تحمل تفسيرك أنت.',
        'The most important thing about a report is not what it shows today but what you keep for comparison tomorrow. Keep one page per week with the nine figures, the top items and the bottom items, one reason for each unusual movement, and one decision you made. After two months these pages become a series, and they are worth more than any ready made report because they carry your own explanation.',
      ) },
      { p: c(
        'وإن لم يكن عندك وقت لكل هذا، فاحتفظ بثلاثة أرقام فقط كل أسبوع: إجمالي المبيعات، عدد الطلبات، وأكثر صنف حركة. ثلاثة أرقام مكتوبة بانتظام أفضل من عشرين رقمًا تُنسى.',
        'If you do not have time for all of this, keep only three numbers each week: total sales, order count, and the fastest moving item. Three numbers written regularly beat twenty numbers forgotten.',
      ) },
      { h: c('أين يساعدك FIHRIST', 'Where FIHRIST helps') },
      { p: c(
        'كل ما سبق يمكن تنفيذه بملف جدول وورقة وقلم. وما يقدمه FIHRIST هنا محدد: مساعد تحليل يقارن بين الفترات وحركة المنتجات ونتائج القنوات، ويشرح ما تدعمه البيانات فقط، ويمكنك دائمًا مراجعة الأرقام نفسها. وتساعدك مقارنة حركة الأصناف بين الفترات على معرفة ما تحرك وما توقف، والصلاحيات تُضبط لكل عضو، والواجهة تعمل بالعربية والإنجليزية. القرارات تبقى قرارك أنت.',
        'All of the above can be done with a spreadsheet, paper, and a pen. What FIHRIST offers here is specific: an analysis assistant that compares periods, product movement, and channel results, and explains only what the data supports, and you can always check the numbers themselves. Comparing item movement across periods helps you see what moved and what stalled, permissions are set per member, and the interface works in Arabic and English. The decisions remain yours.',
      ) },
    ],
    related: ['inventory-tracking-for-small-stores', 'ai-assistant-for-store-customer-replies'],
    solution: 'ai-sales-assistant',
    faq: [
      { q: c('كل كم وقت يجب أن أراجع تقرير المبيعات؟', 'How often should I review the sales report?'),
        a: c(
          'مرة واحدة في الأسبوع تكفي لمعظم المتاجر الصغيرة، في يوم وساعة ثابتين، لأن الأسبوع هو أصغر فترة يعطي رقمًا ذا معنى. المراجعة اليومية الطويلة تُقرأ ولا تُنفَّذ، لكن الإقفال اليومي القصير ضروري لسلامة الأرقام. أما المراجعة الشهرية فمكانها النظر إلى الاتجاه والأصناف والهامش، لا متابعة كل طلب.',
          'Once a week is enough for most small stores, on a fixed day and hour, because a week is the smallest period that gives a meaningful figure. A long daily review gets read and not acted on, but a short daily close is necessary for the numbers to be sound. The monthly review is for direction, assortment, and margin, not for tracking every order.',
        ) },
      { q: c('ما أهم رقم في تقرير المبيعات؟', 'What is the most important number in a sales report?'),
        a: c(
          'لا يوجد رقم واحد أهم من غيره، لكن إن كان لا بد من واحد فهو الربح الإجمالي لا إجمالي المبيعات. الإيراد يخبرك بحجم الحركة، والهامش يخبرك بما يبقى معك. متجر يبيع كثيرًا بهامش ضعيف يتعب أكثر ويكسب أقل. لذلك اقرأ الإيراد والهامش وعدد الطلبات معًا، فهذه الثلاثة معًا تكشف إن كان النمو حقيقيًا أم مجرد حركة.',
          'No single number is more important than the rest, but if you must pick one it is gross profit rather than total sales. Revenue tells you the volume of activity, margin tells you what stays with you. A shop selling a lot at a thin margin works harder and earns less. So read revenue, margin, and order count together, those three reveal whether growth is real or just movement.',
        ) },
      { q: c('كيف أعرف إن كان انخفاض المبيعات بسبب الموسم؟', 'How do I know whether a sales drop is seasonal?'),
        a: c(
          'قارن الشهر نفسه من العام الماضي إن كانت لديك أرقامه، وانظر هل الانخفاض حدث في نفس التوقيت. إن لم تكن لديك أرقام قديمة، فابحث عن علامات أخرى: هل تكرر النمط قبل عطلة أو بعدها، وهل نزلت كل الأصناف أم صنف واحد فقط. وإن كان الانخفاض في صنف واحد بينما الباقي ثابت، فالسبب غالبًا ليس الموسم بل ذلك الصنف. حين لا تتأكد، اكتب السبب غير واضح وراقب أسبوعين.',
          'Compare with the same month last year if you have those figures, and see whether the drop happened at the same time. If you have no old figures, look for other signals: did the pattern repeat before or after a holiday, and did all items fall or only one. If one item fell while the rest held, the cause is probably that item rather than the season. When you are unsure, write cause unclear and watch for two weeks.',
        ) },
      { q: c('هل أحتاج برنامج محاسبة لقراءة تقرير المبيعات؟', 'Do I need accounting software to read a sales report?'),
        a: c(
          'لا، تقرير المبيعات يجيب عن أسئلة البيع والحركة، أما المحاسبة فمكانها الضرائب والقوائم المالية والتزاماتك النظامية. متجر صغير يستطيع أن يبدأ بملف جدول فيه المبيعات والطلبات والأصناف والتكلفة، ويحسب منه المقاييس المذكورة في هذا الدليل. المهم أن تكون البيانات نفسها متسقة، لا أن يكون البرنامج معقدًا. وعندما يكبر العمل، تصبح المحاسبة ضرورة تنظيمية لا شرطًا لقراءة المبيعات.',
          'No, a sales report answers questions about selling and movement, while accounting belongs to tax, financial statements, and your statutory obligations. A small store can start with a spreadsheet holding sales, orders, items, and cost, and calculate the metrics in this guide from it. What matters is that the same data stays consistent, not that the software is complex. As the business grows, accounting becomes an organisational necessity rather than a condition for reading sales.',
        ) },
      { q: c('لماذا يختلف رقم المبيعات في التقرير عن النقد الموجود في الدرج؟', 'Why does the sales figure in the report differ from the cash in the drawer?'),
        a: c(
          'لأنهما يقيسان شيئين مختلفين. التقرير يقيس قيمة ما بيع، والدرج يحتوي ما حُصّل فعلًا. الفرق يظهر عادة من البيع الآجل أو الأونلاين، ومن الشحن المحصَّل، ومن المرتجع الذي دُفع نقدًا، ومن خطأ في الباقي أو خصم لم يُسجل. افصل النقد عن غير النقد في الإقفال، وسجّل كل حركة خارج البيع، وستجد أن الفرق يصغر إلى حد يمكن تفسيره.',
          'Because they measure two different things. The report measures the value of what was sold, the drawer holds what was actually collected. The gap usually comes from credit or online sales, collected shipping, a return paid in cash, and a change error or an unrecorded discount. Separate cash from non cash at closing, record every movement outside a sale, and the gap shrinks to something you can explain.',
        ) },
    ],
  },
};
