import { CHANNELS } from "@/lib/channels";

// The demo inbox is intentionally local to this browser and this test account.
// It never creates provider integrations or sends messages to external services.
const STORAGE_KEY = "fihrist:inbox-demo:dmin@revenueosapp.com:v1";

const CONTACTS = [
  { name: "ملك أحمد", initials: "مل", messages: ["هل المقاس متاح؟", "ممكن أعرف تفاصيل التوصيل؟", "تمام، هأكد الطلب النهارده"] },
  { name: "نور محمد", initials: "نو", messages: ["وصلتني الصور، شكرًا جدًا", "هل اللون البيج متوفر؟", "ممتاز، احجزيلي واحدة"] },
  { name: "سارة محمود", initials: "سا", messages: ["ممكن استبدال المنتج؟", "الطلب وصل امبارح", "شكرًا على سرعة الرد"] },
];

const TELEGRAM_CONTACTS = [
  { name: "هند سامي", initials: "هن", messages: ["مساء الخير، الطلب وصل", "مبسوطة جدًا بالخامة"] },
  { name: "مريم حسن", initials: "مر", messages: ["ممكن أعرف الألوان المتاحة؟", "تمام، شكرًا ليكم"] },
  { name: "أحمد خالد", initials: "أح", messages: ["هل في مقاس أكبر؟", "مستني ردكم"] },
  { name: "مي مصطفى", initials: "مي", messages: ["عايزة أتابع حالة الشحن", "وصلت، تسلموا"] },
  { name: "عمر محمود", initials: "عم", messages: ["السعر شامل التوصيل؟", "تمام"] },
  { name: "سلمى علي", initials: "سل", messages: ["ممكن صورة للون الكحلي؟", "حلو جدًا"] },
  { name: "كريم يوسف", initials: "كر", messages: ["هل المنتج متوفر؟", "احجزوا لي واحدة"] },
  { name: "ياسمين فتحي", initials: "يا", messages: ["شكرًا على سرعة الرد", "هأكد الطلب النهارده"] },
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

function createInitialData() {
  const now = Date.now();
  const formatTime = (value) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return Object.fromEntries(CHANNELS.map((channel, channelIndex) => [channel.id, (channel.id === "telegram" ? [...CONTACTS, ...TELEGRAM_CONTACTS] : CONTACTS).map((contact, contactIndex) => {
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
        if (!missingTelegram.length && !extraFirstMessages.length && !recolorTelegram) return parsed;
        const migrated = {
          ...parsed,
          telegram: [
            ...parsed.telegram.map((conversation) => conversation.id === initialFirst.id && extraFirstMessages.length
              ? { ...conversation, color: telegramAvatarColor(conversation.customer), messages: [...(conversation.messages || []), ...extraFirstMessages], preview: initialFirst.preview, time: initialFirst.time }
              : { ...conversation, color: telegramAvatarColor(conversation.customer) }),
            ...missingTelegram,
          ],
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
