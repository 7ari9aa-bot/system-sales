import React from "react";

// Outline icons drawn in Instagram's style: 24px grid, 2px rounded strokes, filled when active.
function Svg({ size = 24, label, children, className, filled = false, ...rest }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : "true"}
      fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {children}
    </svg>
  );
}

export const IgGlyph = (p) => (
  <Svg {...p}><rect x="2.5" y="2.5" width="19" height="19" rx="5.5" /><circle cx="12" cy="12" r="4.3" /><circle cx="17.4" cy="6.6" r="0.6" fill="currentColor" stroke="none" /></Svg>
);
export const IgMessenger = ({ filled, ...p }) => (
  <Svg {...p}>
    <path d="M12 2.6c-5.3 0-9.4 3.9-9.4 9.1 0 2.7 1.1 5 2.9 6.6.2.1.3.4.3.6l.1 1.7c0 .5.6.9 1.1.7l1.9-.8c.2-.1.4-.1.6 0 .8.2 1.6.3 2.5.3 5.3 0 9.4-3.9 9.4-9.1S17.3 2.6 12 2.6Z" fill={filled ? "currentColor" : "none"} />
    <path d="m6.9 14.4 2.8-4.4c.4-.7 1.4-.9 2-.4l2.2 1.7c.2.2.5.2.7 0l3-2.3c.4-.3.9.2.6.6l-2.8 4.4c-.4.7-1.4.9-2 .4l-2.2-1.7a.6.6 0 0 0-.7 0l-3 2.3c-.4.3-.9-.2-.6-.6Z" fill={filled ? "#fff" : "currentColor"} stroke="none" />
  </Svg>
);
export const IgHeart = ({ filled, ...p }) => (
  <Svg filled={filled} {...p}><path d="M16.8 3.5c-2 0-3.7 1-4.8 2.6C10.9 4.5 9.2 3.5 7.2 3.5 4 3.5 1.8 6 1.8 9c0 5.6 8.6 11 10.2 11.5C13.6 20 22.2 14.6 22.2 9c0-3-2.2-5.5-5.4-5.5Z" /></Svg>
);
export const IgCreate = (p) => (
  <Svg {...p}><rect x="2.5" y="2.5" width="19" height="19" rx="5.5" /><path d="M12 7.5v9M7.5 12h9" /></Svg>
);
export const IgComment = (p) => (
  <Svg {...p}><path d="M20.7 16.3a9.5 9.5 0 1 0-3.4 3.4L21.5 21Z" /></Svg>
);
export const IgShare = (p) => (
  <Svg {...p}><path d="M22 3 9.2 10.1M22 3l-7 18-5.8-10.9L2 6.7Z" /></Svg>
);
export const IgSave = ({ filled, ...p }) => (
  <Svg filled={filled} {...p}><path d="M19.5 21 12 13.6 4.5 21V3h15Z" /></Svg>
);
export const IgMore = (p) => (
  <Svg {...p}><circle cx="6" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="18" cy="12" r="1.3" fill="currentColor" stroke="none" /></Svg>
);
export const IgInfo = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 11v6" /><circle cx="12" cy="7.6" r="0.9" fill="currentColor" stroke="none" /></Svg>
);
export const IgGrid = (p) => (
  <Svg {...p}><rect x="3" y="3" width="18" height="18" /><path d="M9 3v18M15 3v18M3 9h18M3 15h18" /></Svg>
);
export const IgReels = (p) => (
  <Svg {...p}><rect x="2.5" y="2.5" width="19" height="19" rx="5" /><path d="M2.5 8h19M9 2.5 12 8M14.5 2.5 17.5 8" /><path d="m10 11.5 4.5 2.6-4.5 2.6Z" fill="currentColor" /></Svg>
);
export const IgChevronDown = (p) => (<Svg {...p}><path d="m6 9 6 6 6-6" /></Svg>);
export const IgBack = (p) => (<Svg {...p}><path d="M15 5 8 12l7 7" /></Svg>);
export const IgClose = (p) => (<Svg {...p}><path d="M5 5l14 14M19 5 5 19" /></Svg>);
export const IgSearch = (p) => (<Svg {...p}><circle cx="10.5" cy="10.5" r="7" /><path d="m16 16 5.5 5.5" /></Svg>);
export const IgChannels = (p) => (<Svg {...p}><path d="M3 6h18M3 12h18M3 18h18" /></Svg>);
export const IgCarousel = (p) => (
  <Svg {...p} filled><path d="M6 2h11a5 5 0 0 1 5 5v11h-2V7a3 3 0 0 0-3-3H6Z" stroke="none" /><rect x="2" y="6" width="16" height="16" rx="3" stroke="none" /></Svg>
);

/** Instagram's blue verified tick. */
export function IgVerified({ size = 12, label = "Verified" }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} role="img" aria-label={label} className="inline-block shrink-0">
      <path fill="#0095f6" d="M19.998 3.094 14.638 0l-2.972 5.15H5.432v6.354L0 14.64 3.094 20 0 25.359l5.432 3.137v5.905h5.975L14.638 40l5.36-3.094L25.358 40l3.232-5.6h6.162v-6.01L40 25.359 36.905 20 40 14.641l-5.248-3.03v-6.46h-6.419L25.358 0l-5.36 3.094Zm7.415 11.225 2.254 2.287-11.43 11.5-6.835-6.93 2.244-2.258 4.587 4.581 9.18-9.18Z" />
    </svg>
  );
}

/** Instagram's "new message" compose icon (pencil over a square). */
export const IgCompose = (p) => (<Svg {...p}><path d="M12.5 3.5H6a3 3 0 0 0-3 3V18a3 3 0 0 0 3 3h11.5a3 3 0 0 0 3-3v-6" /><path d="m17.8 3.2 3 3-8.3 8.3-3.9.9.9-3.9z" /></Svg>);

/** Smiley shown at the start of Instagram's comment box. */
export const IgEmoji = (p) => (<Svg {...p}><circle cx="12" cy="12" r="9.5" /><path d="M8.5 14.2a4.2 4.2 0 0 0 7 0" /><circle cx="9" cy="9.6" r="0.9" fill="currentColor" stroke="none" /><circle cx="15" cy="9.6" r="0.9" fill="currentColor" stroke="none" /></Svg>);

export const IgPin = (p) => (
  <Svg {...p}><path d="m15.5 3 5.5 5.5-3 .8-3.6 3.6.4 4.1-1.4 1.4-4-4L4 20.2 3.8 20l5.3-5.3-4-4 1.4-1.4 4.1.4 3.6-3.6Z" /></Svg>
);
export const IgMuted = (p) => (
  <Svg {...p}><path d="M11 5 6 9H3v6h3l5 4Z" /><path d="m16 9 5 6M21 9l-5 6" /></Svg>
);
export const IgArchive = (p) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11h14V8M10 12h4" /></Svg>
);

export const IgSettings = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="3.2" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09A1.7 1.7 0 0 0 19.4 15Z" /></Svg>
);
