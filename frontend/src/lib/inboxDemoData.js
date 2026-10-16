import { CHANNELS } from "@/lib/channels";

// The demo inbox is intentionally local to this browser and this test account.
// It never creates provider integrations or sends messages to external services.
const STORAGE_KEY = "fihrist:inbox-demo:dmin@revenueosapp.com:v1";

const CONTACTS = [
  { name: "ملك أحمد", initials: "مل", messages: ["هل المقاس متاح؟", "ممكن أعرف تفاصيل التوصيل؟", "تمام، هأكد الطلب النهارده"] },
  { name: "نور محمد", initials: "نو", messages: ["وصلتني الصور، شكرًا جدًا", "هل اللون البيج متوفر؟", "ممتاز، احجزيلي واحدة"] },
  { name: "سارة محمود", initials: "سا", messages: ["ممكن استبدال المنتج؟", "الطلب وصل امبارح", "شكرًا على سرعة الرد"] },
];

const REPLIES = [
  "أهلًا بيكِ! هراجع المخزون وأرد عليكِ حالًا.",
  "متوفر، والتوصيل خلال يومين إلى ثلاثة أيام.",
  "سعداء بخدمتك، لو احتجتِ أي حاجة إحنا موجودين.",
];

function createInitialData() {
  const now = Date.now();
  const formatTime = (value) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return Object.fromEntries(CHANNELS.map((channel, channelIndex) => [channel.id, CONTACTS.map((contact, contactIndex) => {
    const conversationId = `demo:${channel.id}:${contactIndex + 1}`;
    const createdAt = new Date(now - (channelIndex * 3 + contactIndex) * 7 * 60_000).toISOString();
    const messages = contact.messages.map((text, index) => {
      const messageAt = new Date(now - (contact.messages.length - index) * 4 * 60_000).toISOString();
      return {
        id: `${conversationId}:m${index + 1}`,
        side: index === 1 ? "out" : "in",
        text: index === 1 ? REPLIES[(channelIndex + contactIndex) % REPLIES.length] : text,
        createdAt: messageAt,
        time: formatTime(messageAt),
        status: index === 1 ? "read" : "received",
        senderType: index === 1 ? "agent" : "customer",
      };
    });
    return {
      id: conversationId,
      customer: contact.name,
      initials: contact.initials,
      color: channel.id === "whatsapp" ? whatsappAvatarColor(contact.name) : channel.accent,
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
      if (parsed && CHANNELS.every((channel) => Array.isArray(parsed[channel.id]))) return parsed;
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
