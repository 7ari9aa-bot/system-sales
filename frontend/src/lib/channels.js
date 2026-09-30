// Channel definitions + themed mock conversations for the multi-channel inbox.
// Real channel connections are managed in Settings → Channels; here we model
// which channels are connected and the per-channel chat theme.

export const CHANNELS = [
  {
    id: "whatsapp",
    name: "WhatsApp",
    connected: true,
    icon: "MessageCircle",
    accent: "#25D366",
    theme: {
      headerBg: "#075E54",
      headerText: "#ffffff",
      chatBg: "#E5DDD5",
      out: "#DCF8C6",
      outText: "#111111",
      in: "#ffffff",
      inText: "#111111",
      inputBg: "#f0f2f5",
      inputBorder: "#e9edef",
      checkmarks: true,
      tail: true,
    },
  },
  {
    id: "instagram",
    name: "Instagram",
    connected: true,
    icon: "Instagram",
    accent: "#E1306C",
    theme: {
      headerBg: "linear-gradient(135deg, #515BD4 0%, #8134AF 30%, #DD2A7B 60%, #F58529 100%)",
      headerText: "#ffffff",
      chatBg: "#ffffff",
      out: "linear-gradient(135deg, #833AB4, #E1306C)",
      outText: "#ffffff",
      in: "#EFEFEF",
      inText: "#111111",
      inputBg: "#ffffff",
      inputBorder: "#dbdbdb",
      checkmarks: false,
      tail: false,
    },
  },
  {
    id: "messenger",
    name: "Messenger",
    connected: true,
    icon: "MessagesSquare",
    accent: "#0084FF",
    theme: {
      headerBg: "#0084FF",
      headerText: "#ffffff",
      chatBg: "#ffffff",
      out: "#0084FF",
      outText: "#ffffff",
      in: "#F1F0F0",
      inText: "#111111",
      inputBg: "#f0f2f5",
      inputBorder: "#e9edef",
      checkmarks: true,
      tail: false,
    },
  },
  {
    id: "webchat",
    name: "Web Chat",
    connected: true,
    icon: "MessageSquare",
    accent: "hsl(var(--primary))",
    theme: "app",
  },
  {
    id: "telegram",
    name: "Telegram",
    connected: false,
    icon: "Send",
    accent: "#2AABEE",
    theme: {
      headerBg: "#527DA3",
      headerText: "#ffffff",
      chatBg: "#E7F3FE",
      out: "#E8F5FC",
      outText: "#111111",
      in: "#ffffff",
      inText: "#111111",
      inputBg: "#ffffff",
      inputBorder: "#e1eaf0",
      checkmarks: true,
      tail: false,
    },
  },
  {
    id: "facebook",
    name: "Facebook",
    connected: false,
    icon: "Facebook",
    accent: "#1877F2",
    theme: {
      headerBg: "#1877F2",
      headerText: "#ffffff",
      chatBg: "#ffffff",
      out: "#1877F2",
      outText: "#ffffff",
      in: "#F1F0F0",
      inText: "#111111",
      inputBg: "#f0f2f5",
      inputBorder: "#e9edef",
      checkmarks: true,
      tail: false,
    },
  },
];

export function getChannel(id) {
  return CHANNELS.find((c) => c.id === id) || CHANNELS[0];
}

// Conversations grouped by channel. Customer names are data — shown as-is.
export const CONVERSATIONS_BY_CHANNEL = {
  whatsapp: [
    {
      id: "wa-1", customer: "Nourhan Adel", initials: "NA", color: "#25D366", time: "12:40", unread: 2, status: "waiting", handledBy: "ai",
      preview: "Is the linen shirt available in M?",
      messages: [
        { side: "in", text: "Hi, is the linen shirt available in size M?", time: "12:38" },
        { side: "out", text: "Hi Nourhan! Yes, the Linen Shirt — Sand is in stock in M. Want me to reserve one?", time: "12:39", ai: true, status: "read" },
        { side: "in", text: "Yes please, and delivery to Jeddah?", time: "12:40" },
      ],
    },
    {
      id: "wa-2", customer: "Khaled Mostafa", initials: "KM", color: "#0a7d44", time: "11:05", unread: 0, status: "ai", handledBy: "ai",
      preview: "AI is handling — checking stock",
      messages: [
        { side: "in", text: "Do you ship to Riyadh?", time: "11:03" },
        { side: "out", text: "Yes! 2–3 days for 18 SAR, free over 500. Want to place an order?", time: "11:04", ai: true, status: "delivered" },
      ],
    },
    {
      id: "wa-3", customer: "Mariam Saad", initials: "MS", color: "#1a8f5a", time: "Yesterday", unread: 1, status: "approval", handledBy: "human",
      preview: "AI wants to apply 10% discount",
      messages: [
        { side: "in", text: "Can I get a discount if I order 3?", time: "Yesterday" },
        { side: "out", text: "Let me check with the team for a bulk discount on 3 items…", time: "Yesterday", ai: true, status: "read" },
      ],
    },
  ],
  instagram: [
    {
      id: "ig-1", customer: "@salma.styles", initials: "SS", color: "#E1306C", time: "13:10", unread: 3, status: "waiting", handledBy: "ai",
      preview: "Love the new collection! 💕",
      messages: [
        { side: "in", text: "Love the new collection! 💕", time: "13:08" },
        { side: "in", text: "Is the cream blazer still available?", time: "13:09" },
        { side: "out", text: "Thank you! 💖 Yes it's available — want the link to order?", time: "13:10", ai: true, status: "delivered" },
      ],
    },
    {
      id: "ig-2", customer: "@hanaa.k", initials: "HK", color: "#833AB4", time: "10:22", unread: 0, status: "resolved", handledBy: "human",
      preview: "Order confirmed, thank you! ✨",
      messages: [
        { side: "in", text: "Just placed the order!", time: "10:20" },
        { side: "out", text: "Amazing, order #1042 confirmed ✨ We'll ship tomorrow.", time: "10:21", ai: true, status: "read" },
      ],
    },
  ],
  messenger: [
    {
      id: "ms-1", customer: "Omar Fathy", initials: "OF", color: "#0084FF", time: "14:30", unread: 1, status: "waiting", handledBy: "human",
      preview: "What's your return policy?",
      messages: [
        { side: "in", text: "Hi, what's your return policy?", time: "14:28" },
        { side: "out", text: "Hi Omar! 14-day returns on unworn items with tags. Free pickup in Cairo. 😊", time: "14:29", ai: true, status: "delivered" },
        { side: "in", text: "Great, thanks!", time: "14:30" },
      ],
    },
    {
      id: "ms-2", customer: "Yasmin Tarek", initials: "YT", color: "#0066cc", time: "09:15", unread: 0, status: "ai", handledBy: "ai",
      preview: "AI handling — order tracking",
      messages: [
        { side: "in", text: "Where's my order?", time: "09:12" },
        { side: "out", text: "Order #1038 is out for delivery, arriving today by 6 PM. 📦", time: "09:13", ai: true, status: "read" },
      ],
    },
  ],
  webchat: [
    {
      id: "wc-1", customer: "Site Visitor #2841", initials: "28", color: "hsl(var(--primary))", time: "15:02", unread: 1, status: "waiting", handledBy: "ai",
      preview: "Looking at the wool coat — sizing?",
      messages: [
        { side: "in", text: "Hi, does the wool coat run true to size?", time: "15:00" },
        { side: "out", text: "Hi! It runs slightly snug — we recommend sizing up. Want a size chart?", time: "15:01", ai: true, status: "delivered" },
      ],
    },
  ],
  telegram: [],
  facebook: [],
};

export function conversationsFor(channelId) {
  return CONVERSATIONS_BY_CHANNEL[channelId] || [];
}