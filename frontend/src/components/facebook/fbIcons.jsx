import React from "react";

// Facebook's own marks, drawn as inline SVG. Each one is used by a control that works.
const base = (size) => ({ width: size, height: size, viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" });

export const FbLogo = ({ size = 40 }) => (
  <svg {...base(size)} viewBox="0 0 36 36">
    <path fill="#0866ff" d="M20.181 35.87C29.094 34.791 36 27.202 36 18c0-9.941-8.059-18-18-18S0 8.059 0 18c0 8.442 5.811 15.526 13.652 17.471L14 34h5.5l.681 1.87Z" />
    <path fill="#fff" d="M13.651 35.471v-11.97H9.936V18h3.715v-2.37c0-6.127 2.772-8.964 8.784-8.964 1.138 0 3.103.223 3.91.446v4.983c-.425-.043-1.167-.065-2.081-.065-2.952 0-4.09 1.116-4.09 4.025V18h5.883l-1.008 5.5h-4.867v12.37a18.183 18.183 0 0 1-6.53-.399Z" />
  </svg>
);
export const FbHome = ({ filled, size = 24 }) => (
  <svg {...base(size)} fill="currentColor">{filled
    ? <path d="M12.5 2.2a1 1 0 0 0-1 0L2.8 8.6a1 1 0 0 0-.4.8V21a1 1 0 0 0 1 1H9v-7h6v7h5.6a1 1 0 0 0 1-1V9.4a1 1 0 0 0-.4-.8l-8.7-6.4Z" />
    : <path d="M12 3.3 4 9.2V20h3.5v-6.5h9V20H20V9.2l-8-5.9Zm.6-1.1 8.7 6.4a1 1 0 0 1 .4.8V21a1 1 0 0 1-1 1h-5.6v-7h-6v7H3.4a1 1 0 0 1-1-1V9.4a1 1 0 0 1 .4-.8l8.7-6.4a1 1 0 0 1 1.1 0Z" />}</svg>
);
export const FbMessenger = ({ filled, size = 24 }) => (
  <svg {...base(size)} fill="currentColor">
    <path d="M12 2C6.3 2 2 6.1 2 11.4c0 2.8 1.2 5.2 3.2 6.9V22l3.7-2c1 .3 2 .4 3.1.4 5.7 0 10-4.1 10-9.4S17.7 2 12 2Zm1 12.6-2.6-2.7-5 2.7 5.5-5.8 2.6 2.7 5-2.7-5.5 5.800Z" opacity={filled ? 1 : 0.9} />
  </svg>
);
export const FbBell = ({ filled, size = 24 }) => (
  <svg {...base(size)} fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
    <path d="M18 9a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8ZM13.7 21a2 2 0 0 1-3.4 0" />
  </svg>
);
export const FbChart = ({ filled, size = 24 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth={filled ? 2.6 : 2} strokeLinecap="round"><path d="M5 20V10M12 20V4M19 20v-7" /></svg>
);
export const FbPlus = ({ size = 20 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
);
export const FbLike = ({ filled, size = 20 }) => (
  <svg {...base(size)} fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
    <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4-8a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2.3l-1.2 6.500A2 2 0 0 1 17.8 20H7" />
  </svg>
);
export const FbComment = ({ size = 20 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><path d="M21 12a8.5 8.5 0 0 1-12.3 7.600L3 21l1.5-5.300A8.5 8.5 0 1 1 21 12Z" /></svg>
);
export const FbGlobe = ({ size = 12 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" /></svg>
);
export const FbMore = ({ size = 20 }) => (
  <svg {...base(size)} fill="currentColor"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
);
export const FbClock = ({ size = 20 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const FbChannels = ({ size = 24 }) => (
  <svg {...base(size)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>
);
export const FbPhoto = ({ size = 24 }) => (
  <svg {...base(size)} fill="currentColor">
    <path d="M5 3h14a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3Zm0 2a1 1 0 0 0-1 1v9.6l3.5-3.6a1.5 1.5 0 0 1 2.1 0l2.6 2.6 3.3-4.2a1.5 1.5 0 0 1 2.3 0L20 13.6V6a1 1 0 0 0-1-1H5Zm11 2.2a1.8 1.8 0 1 1 0 3.600 1.8 1.8 0 0 1 0-3.600Z" />
  </svg>
);
export const FbReels = ({ filled, size = 24 }) => (
  <svg {...base(size)} fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="4" />
    <path d="M3 9h18M9 3l3 6M15 3l3 6" />
    <path d="m10.5 13 4 2.4-4 2.4Z" fill="currentColor" />
  </svg>
);

// The small round badge for one reaction kind in a post's summary line. Like keeps Facebook's blue
// thumb; the others are the familiar faces, so a count reads at a glance.
const BADGE = {
  LIKE: { bg: "#0866ff", face: null },
  LOVE: { bg: "#f33e58", face: "❤" },
  HAHA: { bg: "#f7b125", face: "😆" },
  WOW: { bg: "#f7b125", face: "😮" },
  SAD: { bg: "#f7b125", face: "😢" },
  ANGRY: { bg: "#e9710f", face: "😡" },
};
export const FbReactionBadge = ({ kind, size = 18 }) => {
  const b = BADGE[kind] || BADGE.LIKE;
  return (
    <span aria-hidden="true" data-kind={kind} className="grid place-items-center rounded-full text-white ring-2 ring-white" style={{ width: size, height: size, background: b.bg, fontSize: size * 0.62, lineHeight: 1 }}>
      {b.face ?? <FbLike filled size={size * 0.62} />}
    </span>
  );
};
