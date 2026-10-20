// أنماط موحّدة لشاشة إضافة / تعديل المنتج (نفس لغة التصميم في كل عناصر النموذج).

export const PAGE = "relative -mx-2 -my-2 min-h-[calc(100vh-1rem)] overflow-hidden bg-[#f4f2ef] sm:-mx-3";

export const GLOW =
  "pointer-events-none absolute left-[-80px] top-[120px] z-0 h-[320px] w-[320px] rounded-full bg-[radial-gradient(circle,rgba(249,115,22,.18),transparent_70%)] animate-float";

// الرأس: صورة الموديل خلفية + طبقة تدرّج + شريط الأزرار.
export const HERO = "relative flex h-[240px] flex-col justify-end px-5 py-6 sm:h-[300px] sm:px-12 sm:py-10";
export const HERO_MEDIA = "absolute inset-0 z-0 h-full w-full";
export const HERO_SCRIM =
  "absolute inset-0 z-[1] bg-[linear-gradient(0deg,rgba(244,242,239,.96)_8%,rgba(244,242,239,.55)_60%,rgba(244,242,239,.2))]";
export const HERO_BAR = "mt-5 flex flex-wrap gap-3 animate-up";
export const HERO_BTN =
  "inline-flex h-11 cursor-pointer items-center gap-2 rounded-xl border border-[#d9d4cd] bg-white px-5 text-[15px] font-semibold text-[#3a342d] transition-[background-color,box-shadow,border-color] duration-200 hover:bg-[#fbf8f4] hover:shadow-[0_6px_16px_-8px_rgba(60,40,20,.3)] active:bg-[#f1ece5] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f97316] [&_svg]:h-[18px] [&_svg]:w-[18px] [&_svg]:shrink-0 [&_svg]:text-[#f97316]";

// بطاقات الصفحة والشبكة.
export const WRAP = "relative z-[3] mt-[-10px] grid gap-7 px-5 pb-12 sm:px-12 lg:grid-cols-[1fr_340px]";
export const MAIN_COL = "flex min-w-0 flex-col gap-7";
export const CARD =
  "rounded-[18px] border border-[#e6e1da] bg-white shadow-[0_1px_2px_rgba(40,30,20,.05),0_24px_48px_-32px_rgba(40,30,20,.3)]";
export const CARD_PAD = "p-6 sm:p-8";
export const SIDE = "flex h-fit flex-col gap-5 animate-up [animation-delay:.3s]";

// أقسام النموذج.
export const SECTION = "flex flex-col gap-[18px] border-b border-[#eee9e2] pb-7 last:border-b-0 last:pb-0";
export const SECTION_HEAD = "flex flex-wrap items-center gap-2.5";
export const DOT = "h-2.5 w-2.5 shrink-0 rounded-full bg-[#f97316] shadow-[0_0_0_5px_#fff1e6]";
export const SECTION_TITLE = "font-heading text-[17px] font-bold text-[#2a2622]";
export const SECTION_HINT = "text-[12px] text-[#8a8277]";
export const GRID2 = "grid gap-[18px] sm:grid-cols-2";
export const GRID3 = "grid gap-[18px] sm:grid-cols-2 lg:grid-cols-3";

// الحقول.
export const FIELD = "flex flex-col gap-2";
export const LABEL = "text-[13px] font-semibold text-[#6b6358]";

const FIELD_SKIN =
  "rounded-[11px] border border-[#ddd7cf] bg-[#faf9f7] text-[14px] text-[#2a2622] shadow-none transition-[border-color,box-shadow] duration-200 hover:border-[#f5a766] placeholder:text-[#a9a29a]";
const FIELD_FOCUS =
  "focus-visible:border-[#f97316] focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-[#ffe3cc]";

export const INPUT = `${FIELD_SKIN} h-[46px] px-3 py-0 ${FIELD_FOCUS}`;
export const SELECT_TRIGGER = `${FIELD_SKIN} h-[46px] px-3 py-0 focus:border-[#f97316] focus:outline-none focus:ring-[3px] focus:ring-[#ffe3cc]`;
export const TEXTAREA = `${FIELD_SKIN} min-h-[110px] px-3 py-2.5 ${FIELD_FOCUS}`;
export const READONLY =
  "num flex h-[46px] items-center rounded-[11px] border border-[#ddd7cf] bg-[#faf9f7] px-3 text-[14px] font-bold text-[#2a2622]";

// الألوان والمقاسات.
export const CHIPS = "flex flex-wrap gap-2.5";
export const CHIP = `${FIELD_SKIN} flex h-[46px] min-w-[46px] flex-row items-center justify-center gap-2 px-2.5 text-[13px] font-semibold text-[#3a342d] transition-[border-color,background-color,box-shadow] duration-200 hover:border-[#f97316] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f97316] hover:bg-[#faf9f7]`;
export const CHIP_ON = "border-[#f97316] bg-[#fff1e6] hover:bg-[#fff1e6]";
export const SWATCH_DOT =
  "h-[34px] w-[34px] shrink-0 rounded-full border-2 border-white shadow-[0_0_0_1px_#ddd7cf] transition-[box-shadow] duration-200 group-hover:shadow-[0_0_0_2px_#f97316]";
export const PRIMARY_BTN =
  "inline-flex h-11 cursor-pointer items-center gap-2 rounded-xl border-0 bg-[#f97316] px-5 text-[15px] font-bold text-white shadow-[0_10px_20px_-10px_rgba(249,115,22,.7)] transition-[background-color,box-shadow] duration-200 hover:bg-[#ea6a0c] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2a2622]";

// عمود صورة الموديل.
export const PIC = "aspect-[4/5] overflow-hidden rounded-[14px] border border-[#e6e1da] bg-[#eee9e2]";
export const THUMBS = "grid grid-cols-3 gap-3";
export const THUMB =
  "flex aspect-square cursor-pointer items-center justify-center rounded-xl border-[1.5px] border-dashed border-[#cfc8be] bg-[#faf9f7] transition-[border-color,background-color] duration-200 hover:border-[#f97316] hover:bg-[#fff6ee] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f97316] [&_svg]:h-[22px] [&_svg]:w-[22px] [&_svg]:text-[#f97316]";
export const DROP_ZONE =
  "flex h-14 cursor-pointer items-center justify-center gap-2 rounded-xl border-[1.5px] border-dashed border-[#f5a766] bg-[#fff6ee] text-[13px] font-semibold text-[#b45309] transition-[background-color] duration-200 hover:bg-[#ffeedd] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f97316] [&_svg]:h-6 [&_svg]:w-6 [&_svg]:shrink-0 [&_svg]:text-[#f97316]";
export const CTA_ROW = "flex gap-3";
export const CTA_PRIMARY =
  "h-12 flex-1 cursor-pointer rounded-xl border-0 bg-[#f97316] text-[15px] font-bold text-white shadow-[0_10px_20px_-10px_rgba(249,115,22,.7)] transition-[background-color,box-shadow] duration-200 hover:bg-[#ea6a0c] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2a2622]";
export const CTA_ICON =
  "h-12 w-12 shrink-0 cursor-pointer rounded-xl border border-[#d9d4cd] bg-white text-[#3a342d] transition-colors duration-200 hover:bg-[#f6f2ec] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f97316] [&_svg]:h-5 [&_svg]:w-5";