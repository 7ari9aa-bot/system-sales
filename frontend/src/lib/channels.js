// Static channel presentation metadata only. Connection status and all
// conversations/messages are loaded from the authenticated backend API.

export const MESSENGER_CHAT_THEMES = [
  { id: "blue", name: { ar: "أزرق", en: "Blue" }, accent: "#0084FF" },
  { id: "purple", name: { ar: "بنفسجي", en: "Purple" }, accent: "#8B5CF6" },
  { id: "pink", name: { ar: "وردي", en: "Pink" }, accent: "#E64980" },
  { id: "teal", name: { ar: "تركواز", en: "Teal" }, accent: "#0F9D8A" },
  { id: "orange", name: { ar: "برتقالي", en: "Orange" }, accent: "#F47B20" },
  { id: "indigo", name: { ar: "نيلي", en: "Indigo" }, accent: "#5B65D8" },
];

export const CHANNELS = [
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: "MessageCircle",
    accent: "#25D366",
    theme: {
      // CSS variables (whatsapp-theme.css), so the dark mode is one block there.
      headerBg: "var(--wa-bg-panel)",
      headerText: "var(--wa-text)",
      chatBg: "var(--wa-bg-chat)",
      out: "var(--wa-bubble-out)",
      outText: "var(--wa-text)",
      in: "var(--wa-bubble-in)",
      inText: "var(--wa-text)",
      inputBg: "var(--wa-bg-input)",
      inputBorder: "var(--wa-bg-chip)",
      divider: "var(--wa-divider)",
      secondaryText: "var(--wa-text-secondary)",
      checkmarks: true,
      tail: true,
    },
  },
  {
    id: "instagram",
    name: "Instagram",
    icon: "Instagram",
    accent: "#E1306C",
    theme: {
      headerBg: "#ffffff",
      headerText: "#000000",
      chatBg: "#ffffff",
      out: "#4A5DF9",
      outText: "#ffffff",
      in: "#F3F5F7",
      inText: "#000000",
      inputBg: "#ffffff",
      inputBorder: "#dbdbdb",
      divider: "#dbdbdb",
      // Tokens read from Instagram's own production CSS (static.cdninstagram.com):
      // --ig-outgoing-message-bubble 74,93,249 (flat, NOT a gradient), --ig-incoming-message-bubble
      // 243,245,247, --ig-primary-text #000, --ig-secondary-text #737373, --ig-separator #dbdbdb.
      secondaryText: "#737373",
      darkOut: "#4A5DF9",
      darkIn: "#25292E",
      darkBg: "#0C1014",
      darkText: "#F5F5F5",
      bubbleRadius: 18, // pill-like corner as drawn by Instagram's own web chat (compared live, 2026-11-18)
      checkmarks: false,
      tail: false,
    },
  },
  {
    id: "messenger",
    name: "Messenger",
    icon: "MessagesSquare",
    accent: "#0084FF",
    theme: {
      headerBg: "#ffffff",
      headerText: "#050505",
      chatBg: "#ffffff",
      out: "#0084FF",
      outText: "#ffffff",
      in: "#F0F0F0",
      inText: "#050505",
      inputBg: "#ffffff",
      inputBorder: "#E4E6EB",
      divider: "#E4E6EB",
      secondaryText: "#65676B",
      checkmarks: true,
      tail: false,
    },
  },
  {
    id: "webchat",
    name: "Web Chat",
    icon: "MessageSquare",
    accent: "hsl(var(--primary))",
    theme: "app",
  },
  {
    id: "telegram",
    name: "Telegram",
    icon: "Send",
    accent: "#2AABEE",
    theme: {
      headerBg: "#ffffff",
      headerText: "#222222",
      chatBg: "#a9cf9a",
      out: "#efffe6",
      outText: "#111111",
      in: "#ffffff",
      inText: "#111111",
      inputBg: "#ffffff",
      inputBorder: "#e4e9eb",
      divider: "#e6e8ea",
      secondaryText: "#7f9db8",
      checkColor: "#3390ec",
      checkmarks: true,
      tail: true,
    },
  },
  {
    id: "facebook",
    name: "Facebook",
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
