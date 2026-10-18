import { CHANNELS } from "@/lib/channels";

// The demo inbox is intentionally local to this browser and this test account.
// It never creates provider integrations or sends messages to external services.
const STORAGE_KEY = "fihrist:inbox-demo:dmin@revenueosapp.com:v1";
const FACEBOOK_POSTS_STORAGE_KEY = "fihrist:facebook-page-posts-demo:dmin@revenueosapp.com:v1";
const INSTAGRAM_POSTS_STORAGE_KEY = "fihrist:instagram-posts-demo:dmin@revenueosapp.com:v1";

const CONTACTS = [
  { name: "ملك أحمد", initials: "مل", telegramAvatar: "malak-ahmed", messages: ["هل المقاس متاح؟", "ممكن أعرف تفاصيل التوصيل؟", "تمام، هأكد الطلب النهارده"] },
  { name: "نور محمد", initials: "نو", telegramAvatar: "noor-mohamed", messages: ["وصلتني الصور، شكرًا جدًا", "هل اللون البيج متوفر؟", "ممتاز، احجزيلي واحدة"] },
  { name: "سارة محمود", initials: "سا", telegramAvatar: "sara-mahmoud", messages: ["ممكن استبدال المنتج؟", "الطلب وصل امبارح", "شكرًا على سرعة الرد"] },
];

const TELEGRAM_CONTACTS = [
  { name: "هند سامي", initials: "هن", telegramAvatar: "hind-sami", messages: ["مساء الخير، الطلب وصل", "مبسوطة جدًا بالخامة"] },
  { name: "مريم حسن", initials: "مر", telegramAvatar: "maryam-hassan", messages: ["ممكن أعرف الألوان المتاحة؟", "تمام، شكرًا ليكم"] },
  { name: "أحمد خالد", initials: "أح", telegramAvatar: "ahmed-khaled", messages: ["هل في مقاس أكبر؟", "مستني ردكم"] },
  { name: "مي مصطفى", initials: "مي", telegramAvatar: "mai-mostafa", messages: ["عايزة أتابع حالة الشحن", "وصلت، تسلموا"] },
  { name: "عمر محمود", initials: "عم", telegramAvatar: "omar-mahmoud", messages: ["السعر شامل التوصيل؟", "تمام"] },
  { name: "سلمى علي", initials: "سل", telegramAvatar: "salma-ali", messages: ["ممكن صورة للون الكحلي؟", "حلو جدًا"] },
  { name: "كريم يوسف", initials: "كر", telegramAvatar: "karim-youssef", messages: ["هل المنتج متوفر؟", "احجزوا لي واحدة"] },
  { name: "ياسمين فتحي", initials: "يا", telegramAvatar: "yasmin-fathy", messages: ["شكرًا على سرعة الرد", "هأكد الطلب النهارده"] },
];

const TELEGRAM_SAMPLE_MESSAGES = [
  { text: "أهلًا، محتاجة أعرف المقاس متاح؟", side: "in", senderType: "customer" },
  { text: "أهلًا بيكِ! المقاس متاح، أساعدك في أي حاجة تانية؟", side: "out", senderType: "agent" },
  { text: "ممكن أعرف تفاصيل التوصيل؟", side: "in", senderType: "customer" },
  { text: "التوصيل خلال يومين إلى ثلاثة أيام.", side: "out", senderType: "agent" },
  { text: "تمام، هأكد الطلب النهارده 😊", side: "in", senderType: "customer" },
  { text: "شكرًا ليكِ، مستنيين تأكيدك 🌷", side: "out", senderType: "agent" },
  { text: "أكدت الطلب، متشكرة جدًا", side: "in", senderType: "customer" },
  { text: "العفو، تحت أمرك في أي وقت!", side: "out", senderType: "agent" },
];

const REPLIES = [
  "أهلًا بيكِ! هراجع المخزون وأرد عليكِ حالًا.",
  "متوفر، والتوصيل خلال يومين إلى ثلاثة أيام.",
  "سعداء بخدمتك، لو احتجتِ أي حاجة إحنا موجودين.",
];

function createDemoFacebookPosts() {
  return [
    {
      id: "demo:facebook-post:collection",
      pageName: "فهرست | FIHRIST",
      pageAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "منذ ساعتين",
      text: "وصلت تشكيلة الموسم الجديدة 🌿 خامات مريحة وألوان هادئة تناسب كل يوم. شوفي المجموعة واختاري القطعة الأقرب لذوقك.",
      mediaUrl: "/facebook-posts/spring-collection.png",
      reactionCount: 28,
      shareCount: 3,
      comments: [
        {
          id: "demo:facebook-comment:collection-1",
          author: "ملك أحمد",
          avatarUrl: "/telegram-avatars/malak-ahmed.png",
          timeLabel: "منذ ٤٥ دقيقة",
          text: "البلوزة الكحلي متاحة بمقاس M؟",
          likes: 2,
          replies: [
            { id: "demo:facebook-reply:collection-1-customer", author: "ملك أحمد", avatarUrl: "/telegram-avatars/malak-ahmed.png", timeLabel: "منذ ٣٥ دقيقة", text: "ممتاز، هبعتلكم رسالة بالتفاصيل." },
            { id: "demo:facebook-reply:collection-1-page", author: "فهرست | FIHRIST", avatarUrl: "/fihrist-mark.svg", timeLabel: "منذ ٣٠ دقيقة", text: "أهلًا يا ملك، متاحة بمقاس M 💙 ابعتي لنا رسالة ونبعت لك صورها.", isPage: true, isAgent: true },
          ],
        },
        {
          id: "demo:facebook-comment:collection-2",
          author: "نور محمد",
          avatarUrl: "/telegram-avatars/noor-mohamed.png",
          timeLabel: "منذ ٣٠ دقيقة",
          text: "الألوان كلها جميلة، بالتوفيق دايمًا 😍",
          likes: 1,
          replies: [{ id: "demo:facebook-reply:collection-2-page", author: "فهرست | FIHRIST", avatarUrl: "/fihrist-mark.svg", timeLabel: "منذ ٢٥ دقيقة", text: "شكرًا لذوقك يا نور، رأيك يسعدنا جدًا 🌷", isPage: true }],
        },
      ],
    },
    {
      id: "demo:facebook-post:delivery",
      pageName: "فهرست | FIHRIST",
      pageAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "أمس · ٦:٢٠ م",
      text: "طلبك لحد باب البيت 📦 بنجهز كل طلب بعناية، والتوصيل متاح لكل المحافظات خلال يومين إلى ثلاثة أيام.",
      mediaUrl: "/facebook-posts/careful-packing.png",
      reactionCount: 16,
      shareCount: 1,
      comments: [
        {
          id: "demo:facebook-comment:delivery-1",
          author: "سارة محمود",
          avatarUrl: "/telegram-avatars/sara-mahmoud.png",
          timeLabel: "منذ ٤ ساعات",
          text: "التوصيل لأسيوط بياخد كام يوم؟",
          likes: 0,
          replies: [],
        },
        {
          id: "demo:facebook-comment:delivery-2",
          author: "عمر محمود",
          avatarUrl: "/telegram-avatars/omar-mahmoud.png",
          timeLabel: "منذ ٥ ساعات",
          text: "وصلني الطلب والتغليف ممتاز، شكرًا لكم!",
          likes: 3,
          replies: [{ id: "demo:facebook-reply:delivery-2-page", author: "فهرست | FIHRIST", avatarUrl: "/fihrist-mark.svg", timeLabel: "منذ ٤ ساعات", text: "بالهناء يا عمر، شكرًا إنك شاركتنا رأيك 🤍", isPage: true }],
        },
      ],
    },
    {
      id: "demo:facebook-post:colors",
      pageName: "فهرست | FIHRIST",
      pageAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "١٥ أكتوبر · ١١:٠٥ ص",
      text: "محتارين نضيف أنهي لون للمجموعة الجاية؟ اكتبوا اختياركم في التعليقات: زيتي، رملي، ولا أزرق هادي 💬",
      mediaUrl: null,
      reactionCount: 34,
      shareCount: 5,
      comments: [
        {
          id: "demo:facebook-comment:colors-1",
          author: "هند سامي",
          avatarUrl: "/telegram-avatars/hind-sami.png",
          timeLabel: "١٥ أكتوبر · ١٢:١٠ م",
          text: "الزيتي هيكون تحفة!",
          likes: 4,
          replies: [{ id: "demo:facebook-reply:colors-1-page", author: "فهرست | FIHRIST", avatarUrl: "/fihrist-mark.svg", timeLabel: "١٥ أكتوبر · ١٢:٣٠ م", text: "وصل صوتك يا هند 💚 هنخليه ضمن الاختيارات.", isPage: true }],
        },
        {
          id: "demo:facebook-comment:colors-2",
          author: "كريم يوسف",
          avatarUrl: "/telegram-avatars/karim-youssef.png",
          timeLabel: "١٥ أكتوبر · ١:٠٠ م",
          text: "الأزرق الهادي، هيليق على حاجات كتير.",
          likes: 2,
          replies: [],
        },
      ],
    },
  ];
}

export function loadDemoFacebookPosts() {
  if (typeof window === "undefined") return createDemoFacebookPosts();
  try {
    const saved = window.localStorage.getItem(FACEBOOK_POSTS_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        let migrated = false;
        const posts = parsed.map((post) => ({
          ...post,
          comments: (post.comments || []).map((comment) => ({
            ...comment,
            replies: (comment.replies || []).map((reply) => {
              if (reply.id !== "demo:facebook-reply:collection-1-page" || reply.isAgent) return reply;
              migrated = true;
              return { ...reply, isAgent: true };
            }),
          })),
        }));
        if (migrated) saveDemoFacebookPosts(posts);
        return posts;
      }
    }
  } catch {
    // Use the bundled sample page when local demo storage is unavailable.
  }
  const posts = createDemoFacebookPosts();
  saveDemoFacebookPosts(posts);
  return posts;
}

export function saveDemoFacebookPosts(posts) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(FACEBOOK_POSTS_STORAGE_KEY, JSON.stringify(posts)); } catch { /* local page demo is optional */ }
}

function createDemoInstagramPosts() {
  return [
    {
      id: "demo:instagram-post:collection",
      accountName: "fihrist.store",
      accountAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "منذ ساعتين",
      text: "وصلت تشكيلة الصيف الجديدة 🌿 ألوان خفيفة وتفاصيل تكمّل إطلالتك. أنهي قطعة عجبتكم أكتر؟ #تشكيلة_جديدة",
      mediaUrl: "/facebook-posts/spring-collection.png",
      mediaType: "image",
      likes: 1240,
      comments: [
        {
          id: "demo:instagram-comment:collection-1",
          author: "منّة رضا",
          handle: "menna.reeda",
          avatarUrl: "/telegram-avatars/malak-ahmed.png",
          timeLabel: "منذ ٢٥ دقيقة",
          text: "اللون الأبيض متوفر منه؟ 😍",
          likes: 6,
          replies: [
            {
              id: "demo:instagram-reply:collection-1-agent",
              author: "fihrist.store",
              handle: "fihrist.store",
              avatarUrl: "/fihrist-mark.svg",
              timeLabel: "منذ ١٨ دقيقة",
              text: "أهلًا منّة، متوفر حاليًا 🤍 ابعتي لنا رسالة خاصة ونساعدك في اختيار المقاس.",
              likes: 1,
              isPage: true,
              isAgent: true,
            },
          ],
        },
        {
          id: "demo:instagram-comment:collection-2",
          author: "نور محمد",
          handle: "noor.mohamed",
          avatarUrl: "/telegram-avatars/noor-mohamed.png",
          timeLabel: "منذ ٤٠ دقيقة",
          text: "التفاصيل جميلة جدًا، مستنية أشوف باقي الألوان ✨",
          likes: 3,
          replies: [],
        },
      ],
    },
    {
      id: "demo:instagram-post:delivery",
      accountName: "fihrist.store",
      accountAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "أمس",
      text: "كل طلب بيتجهز بحب ويوصل لحد بابك 📦 الشحن متاح لكل المحافظات.",
      mediaUrl: "/facebook-posts/careful-packing.png",
      mediaType: "image",
      likes: 864,
      comments: [
        {
          id: "demo:instagram-comment:delivery-1",
          author: "سارة محمود",
          handle: "sara.mhmoud",
          avatarUrl: "/telegram-avatars/sara-mahmoud.png",
          timeLabel: "منذ ٣ ساعات",
          text: "التوصيل للمنصورة بياخد قد إيه؟",
          likes: 2,
          replies: [],
        },
        {
          id: "demo:instagram-comment:delivery-2",
          author: "هند سامي",
          handle: "hind.samy",
          avatarUrl: "/telegram-avatars/hind-sami.png",
          timeLabel: "منذ ٥ ساعات",
          text: "وصلني الأوردر والتغليف تحفة 🤍",
          likes: 8,
          replies: [
            {
              id: "demo:instagram-reply:delivery-2-page",
              author: "fihrist.store",
              handle: "fihrist.store",
              avatarUrl: "/fihrist-mark.svg",
              timeLabel: "منذ ٤ ساعات",
              text: "مبروك عليكِ يا هند، شكرًا إنك شاركتينا رأيك 🤍",
              likes: 0,
              isPage: true,
              isAgent: false,
            },
          ],
        },
      ],
    },
    {
      id: "demo:instagram-post:colors",
      accountName: "fihrist.store",
      accountAvatarUrl: "/fihrist-mark.svg",
      timeLabel: "١٥ أكتوبر",
      text: "محتارين نضيف أنهي لون للمجموعة الجاية؟ اكتبوا اختياركم في التعليقات 💬",
      mediaUrl: null,
      mediaType: null,
      likes: 342,
      comments: [
        {
          id: "demo:instagram-comment:colors-1",
          author: "كريم يوسف",
          handle: "karim.youssef",
          avatarUrl: "/telegram-avatars/karim-youssef.png",
          timeLabel: "١٥ أكتوبر",
          text: "الأزرق الهادي هيليق على كل حاجة.",
          likes: 4,
          replies: [],
        },
      ],
    },
  ];
}

export function loadDemoInstagramPosts() {
  if (typeof window === "undefined") return createDemoInstagramPosts();
  try {
    const saved = window.localStorage.getItem(INSTAGRAM_POSTS_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {
    // Use the bundled sample account when local demo storage is unavailable.
  }
  const posts = createDemoInstagramPosts();
  saveDemoInstagramPosts(posts);
  return posts;
}

export function saveDemoInstagramPosts(posts) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(INSTAGRAM_POSTS_STORAGE_KEY, JSON.stringify(posts)); } catch { /* local page demo is optional */ }
}

function createInitialData() {
  const now = Date.now();
  const formatTime = (value) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return Object.fromEntries(CHANNELS.map((channel, channelIndex) => [channel.id, (channel.id === "telegram" ? [...CONTACTS, ...TELEGRAM_CONTACTS] : channel.id === "facebook" ? [] : CONTACTS).map((contact, contactIndex) => {
    const conversationId = `demo:${channel.id}:${contactIndex + 1}`;
    const createdAt = new Date(now - (channelIndex * 3 + contactIndex) * 7 * 60_000).toISOString();
    const samples = channel.id === "telegram" && contactIndex === 0
      ? TELEGRAM_SAMPLE_MESSAGES
      : contact.messages.map((text, index) => ({ text: index === 1 ? REPLIES[(channelIndex + contactIndex) % REPLIES.length] : text, side: index === 1 ? "out" : "in", senderType: index === 1 ? "agent" : "customer" }));
    const messages = samples.map((sample, index) => {
      const messageAt = new Date(now - (samples.length - index) * 4 * 60_000).toISOString();
      return {
        id: `${conversationId}:m${index + 1}`,
        side: sample.side,
        text: sample.text,
        createdAt: messageAt,
        time: formatTime(messageAt),
        status: sample.side === "out" ? "read" : "received",
        senderType: sample.senderType,
      };
    });
    return {
      id: conversationId,
      customer: contact.name,
      initials: contact.initials,
      ...(channel.id === "telegram" && { avatarUrl: `/telegram-avatars/${contact.telegramAvatar}.png` }),
      ...(channel.id === "messenger" && { avatarUrl: `/telegram-avatars/${contact.telegramAvatar}.png` }),
      ...(channel.id === "instagram" && { avatarUrl: `/telegram-avatars/${contact.telegramAvatar}.png`, folder: ["primary", "general", "requests"][contactIndex % 3] }),
      color: channel.id === "whatsapp" ? whatsappAvatarColor(contact.name) : channel.id === "telegram" ? telegramAvatarColor(contact.name) : channel.accent,
      channel: channel.id,
      preview: messages.at(-1)?.text || "",
      status: "waiting",
      backendStatus: "open",
      assigneeUserId: null,
      unread: contactIndex === 0 ? 1 : 0,
      time: formatTime(createdAt),
      createdAt,
      messages,
      demo: true,
    };
  })]));
}

const AVATAR_COLORS = ["#f3d7c5", "#ddd9f2", "#d4e9dd", "#f2dce0", "#d6e6f4", "#efe8c9"];
const TELEGRAM_AVATAR_COLORS = ["#F59E42", "#E96767", "#53A9D7", "#35B96F", "#D968A7", "#8567D4", "#36A6A8", "#E07B4B"];

function telegramAvatarColor(value) {
  let hash = 0;
  for (const char of String(value || "contact")) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return TELEGRAM_AVATAR_COLORS[(hash >>> 0) % TELEGRAM_AVATAR_COLORS.length];
}

function whatsappAvatarColor(value) {
  let hash = 0;
  for (const char of String(value || "contact")) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return AVATAR_COLORS[(hash >>> 0) % AVATAR_COLORS.length];
}

export function isDemoConversation(id) {
  return String(id || "").startsWith("demo:");
}

export function loadDemoInbox() {
  if (typeof window === "undefined") return createInitialData();
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed && CHANNELS.every((channel) => Array.isArray(parsed[channel.id]))) {
        const knownTelegramIds = new Set(parsed.telegram.map((conversation) => conversation.id));
        const initialTelegram = createInitialData().telegram;
        const missingTelegram = initialTelegram.filter((conversation) => !knownTelegramIds.has(conversation.id));
        const initialFirst = initialTelegram[0];
        const savedFirst = parsed.telegram.find((conversation) => conversation.id === initialFirst.id);
        const extraFirstMessages = savedFirst
          ? initialFirst.messages.filter((message) => !(savedFirst.messages || []).some((savedMessage) => savedMessage.id === message.id))
          : [];
        const recolorTelegram = parsed.telegram.some((conversation) => conversation.color !== telegramAvatarColor(conversation.customer));
        const initialTelegramById = new Map(initialTelegram.map((conversation) => [conversation.id, conversation]));
        const addTelegramAvatars = parsed.telegram.some((conversation) => initialTelegramById.has(conversation.id) && !conversation.avatarUrl);
        const initialMessengerById = new Map(createInitialData().messenger.map((conversation) => [conversation.id, conversation]));
        const addMessengerAvatars = parsed.messenger.some((conversation) => initialMessengerById.has(conversation.id) && !conversation.avatarUrl);
        const initialInstagramById = new Map(createInitialData().instagram.map((conversation) => [conversation.id, conversation]));
        const updateInstagramProfiles = parsed.instagram.some((conversation) => initialInstagramById.has(conversation.id) && (!conversation.avatarUrl || !conversation.folder));
        const removeSeedFacebookDms = parsed.facebook.length > 0;
        if (!missingTelegram.length && !extraFirstMessages.length && !recolorTelegram && !addTelegramAvatars && !addMessengerAvatars && !updateInstagramProfiles && !removeSeedFacebookDms) return parsed;
        const migrated = {
          ...parsed,
          facebook: [],
          instagram: parsed.instagram.map((conversation) => {
            const initial = initialInstagramById.get(conversation.id);
            return initial ? { ...conversation, avatarUrl: conversation.avatarUrl || initial.avatarUrl, folder: conversation.folder || initial.folder } : conversation;
          }),
          telegram: [
            ...parsed.telegram.map((conversation) => {
              const initialConversation = initialTelegramById.get(conversation.id);
              return {
                ...conversation,
                color: telegramAvatarColor(conversation.customer),
                avatarUrl: conversation.avatarUrl || initialConversation?.avatarUrl,
                ...(conversation.id === initialFirst.id && extraFirstMessages.length ? {
                  messages: [...(conversation.messages || []), ...extraFirstMessages],
                  preview: initialFirst.preview,
                  time: initialFirst.time,
                } : {}),
              };
            }),
            ...missingTelegram,
          ],
          messenger: parsed.messenger.map((conversation) => {
            const initial = initialMessengerById.get(conversation.id);
            return initial ? { ...conversation, avatarUrl: conversation.avatarUrl || initial.avatarUrl } : conversation;
          }),
        };
        saveDemoInbox(migrated);
        return migrated;
      }
    }
  } catch {
    // Use a fresh sample inbox when saved browser data is unavailable.
  }
  const initial = createInitialData();
  saveDemoInbox(initial);
  return initial;
}

export function saveDemoInbox(data) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch { /* demo data is optional */ }
}
