// Original SVG icons for the WhatsApp-style inbox.
//
// These are drawn from scratch (simple geometry, 24px grid, 1.8 stroke) to sit
// in the same visual family as a chat app's toolbar. They are NOT copies of
// Meta's artwork: those files are Meta's property and cannot be redistributed.
import React from "react";

function Svg({ size = 24, children, className, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...rest}
    >
      {children}
    </svg>
  );
}

export const PlusIcon = (p) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const EmojiIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 14.2c.8 1.2 2 1.9 3.5 1.9s2.7-.7 3.5-1.9" />
    <circle cx="9" cy="9.8" r=".6" fill="currentColor" />
    <circle cx="15" cy="9.8" r=".6" fill="currentColor" />
  </Svg>
);

export const MicIcon = (p) => (
  <Svg {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" />
  </Svg>
);

// A paper plane, pointing right (flipped for RTL by the caller when needed).
export const SendIcon = (p) => (
  <Svg {...p} fill="currentColor" stroke="none">
    <path d="M3.4 20.4 21 12 3.4 3.6l-.02 6.5L15 12 3.38 13.9z" />
  </Svg>
);

export const SearchIcon = (p) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </Svg>
);

export const BackIcon = (p) => (
  <Svg {...p}>
    <path d="M15 5 8 12l7 7" />
  </Svg>
);

export const MoreIcon = (p) => (
  <Svg {...p} fill="currentColor" stroke="none">
    <circle cx="12" cy="5.5" r="1.7" />
    <circle cx="12" cy="12" r="1.7" />
    <circle cx="12" cy="18.5" r="1.7" />
  </Svg>
);

export const ChevronDownIcon = (p) => (
  <Svg {...p}>
    <path d="m6 9 6 6 6-6" />
  </Svg>
);

export const ReplyIcon = (p) => (
  <Svg {...p}>
    <path d="M10 8 4 13l6 5v-3.2c5 0 8 1.2 10 4.2-.6-5.6-3.6-9-10-9.2z" />
  </Svg>
);

export const ClockIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </Svg>
);

export const AlertIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5M12 16.4v.2" />
  </Svg>
);

export const BlockedIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="m6.4 6.4 11.2 11.2" />
  </Svg>
);

export const CameraIcon = (p) => (
  <Svg {...p}>
    <path d="M4 8h3l1.5-2h7L17 8h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </Svg>
);

export const FileIcon = (p) => (
  <Svg {...p}>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4" />
  </Svg>
);

export const PinIcon = (p) => (
  <Svg {...p}>
    <path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z" />
    <circle cx="12" cy="10" r="2.3" />
  </Svg>
);

export const UserIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="8.5" r="3.5" />
    <path d="M5 20c.8-3.5 3.5-5.5 7-5.5s6.2 2 7 5.5" />
  </Svg>
);

// Single tick, and the double tick used for delivered / read.
export const TickIcon = ({ size = 16, ...p }) => (
  <svg width={size} height={size * 0.75} viewBox="0 0 16 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...p}>
    <path d="m2 6.5 3.2 3.2L12 2.5" />
  </svg>
);

export const DoubleTickIcon = ({ size = 18, ...p }) => (
  <svg width={size} height={size * 0.667} viewBox="0 0 18 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...p}>
    <path d="m1.5 6.5 3.2 3.2L11 2.5M7 9.7l.7.7L14.5 2.5" />
  </svg>
);

// The channel badge: a speech bubble with a handset, in the channel's green.
// An original mark that evokes "a phone chat" — not Meta's logo.
export function WhatsAppChannelBadge({ size = 20, className, title }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : "true"} focusable="false" className={className}>
      <path d="M12 1.8a10.2 10.2 0 0 0-8.7 15.5L1.8 22.2l5-1.3A10.2 10.2 0 1 0 12 1.8z" fill="currentColor" />
      {/* A bold handset: thick enough to stay legible at 20px. */}
      <path d="M8.3 6.2c.5-.5 1.3-.3 1.6.3l1.1 2.3c.2.4.1.9-.2 1.2l-.8.8c.8 1.7 2 2.9 3.7 3.7l.8-.8c.3-.3.8-.4 1.2-.2l2.3 1.1c.6.3.8 1.1.3 1.6-1 1.2-2.4 1.8-3.9 1.4-4.1-1-6.7-3.6-7.7-7.7-.3-1.5.2-2.9 1.6-3.7z" fill="#fff" />
    </svg>
  );
}

export const CopyIcon = (p) => (
  <Svg {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
  </Svg>
);
