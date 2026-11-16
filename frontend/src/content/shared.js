/**
 * Shared marketing content across all markets (Layer 1).
 * Used when a country does not provide a specific override.
 */

export const sharedContent = {
  ar: {
    hero: {
      kicker: 'نظام تشغيل المبيعات المتكامل للمتاجر',
      title: 'من محادثة العميل إلى إتمام البيع في مسار واحد',
      body: 'اربط محادثات WhatsApp وInstagram والويب ببيانات المنتجات، الطلبات، الكاشير والمخزون، مع أدوات ذكية لمتابعة الأداء.',
      primaryCta: 'ابدأ مجاناً الآن',
      secondaryCta: 'احجز عرضاً توضيحياً',
    },
    valueProps: [
      {
        id: 'conversations',
        title: 'صندوق محادثات موحّد',
        description: 'اجمع رسائل واتساب وإنستجرام وماسنجر في شاشة واحدة لكل فريق المبيعات دون تشتت.',
      },
      {
        id: 'orders',
        title: 'تنفيذ سريع للطلبات',
        description: 'أنشئ الطلب بضغطة زر داخل المحادثة مباشرة مع تحديث المخزون وحساب الإجمالي.',
      },
      {
        id: 'pos',
        title: 'كاشير ومخزون حي',
        description: 'ربط لحظي بين مبيعات المحل والأونلاين، مع جرد دقيق وتنبيهات نواقص فورية.',
      },
    ],
    faq: [
      {
        id: 'what_is_fihrist',
        q: 'ما هو نظام FIHRIST؟',
        a: 'FIHRIST هو نظام تشغيل مبيعات شامل يربط قنوات محادثات العملاء (واتساب، إنستجرام، فيسبوك) بإدارة الطلبات والكاشير ونقاط البيع والمخزون في شاشة واحدة.',
      },
      {
        id: 'how_to_start',
        q: 'كيف أبدأ استخدام النظام؟',
        a: 'يمكنك إنشاء حساب تجريبي مجاني خلال دقيقة واحدة، واختيار دولتك وبدء ربط قنوات البيع مباشرة.',
      },
      {
        id: 'data_security',
        q: 'كيف يتم تأمين بيانات المتجر والعملاء؟',
        a: 'نستخدم عزل بيانات كامل لكل متجر (Row Level Security)، وتشفير البيانات أثناء النقل والتخزين، مع صلاحيات مخصصة لكل موظف.',
      },
    ],
    badges: {
      trial: 'تجربة مجانية لمدة 14 يوماً بدون بطاقة بنكية',
      support: 'دعم فني مخصص باللغة العربية',
    },
  },
  en: {
    hero: {
      kicker: 'Sales Operating System for Modern Stores',
      title: 'From customer conversation to closed sale in one connected journey',
      body: 'Connect WhatsApp, Instagram, and web chat with catalog, orders, cashier POS, and live inventory with smart follow-up tools.',
      primaryCta: 'Start Free Now',
      secondaryCta: 'Book a Demo',
    },
    valueProps: [
      {
        id: 'conversations',
        title: 'Unified Inbox',
        description: 'Manage WhatsApp, Instagram, and Messenger in one inbox for your entire sales team.',
      },
      {
        id: 'orders',
        title: 'Fast In-Chat Orders',
        description: 'Generate orders directly inside conversations with automated inventory sync.',
      },
      {
        id: 'pos',
        title: 'Live POS & Stock',
        description: 'Real-time synchronization between in-store POS and online orders with low-stock alerts.',
      },
    ],
    faq: [
      {
        id: 'what_is_fihrist',
        q: 'What is FIHRIST?',
        a: 'FIHRIST is an all-in-one sales operating system connecting customer chat channels with order management, POS, and inventory in a unified workspace.',
      },
      {
        id: 'how_to_start',
        q: 'How do I get started?',
        a: 'You can create a free trial account in under a minute, select your market, and start connecting channels right away.',
      },
      {
        id: 'data_security',
        q: 'How is store and customer data secured?',
        a: 'We enforce full multi-tenant isolation via Postgres Row Level Security, encrypt data in transit and at rest, and offer granular team roles.',
      },
    ],
    badges: {
      trial: '14-day free trial, no credit card required',
      support: 'Dedicated bilingual technical support',
    },
  },
};
