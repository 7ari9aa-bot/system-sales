// أنماط موحّدة لجداول النظام: أزرار، حقول رقيقة، خلايا، ولوحة جدول برأس داكن.
// تُستخدم في شاشات الملصقات والموردين والمشتريات ومرتجعات الموردين لتظهر بنفس الشكل.

export const BTN =
  "h-auto cursor-pointer rounded-md border border-[#DED8CD] bg-white px-3 py-2 text-[12px] font-normal text-[#33322E] shadow-none transition-[background-color,box-shadow,color] duration-150 hover:bg-[#FDEBD8] hover:text-[#33322E] active:bg-[#F8D9B8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";

export const BTN_PRIMARY =
  "h-auto cursor-pointer gap-2 rounded-md border border-[#E8761A] bg-[#E8761A] px-4 py-2.5 text-[13px] font-semibold text-white shadow-none transition-[background-color,border-color] duration-150 hover:border-[#D1650F] hover:bg-[#D1650F] hover:text-white active:border-[#B9560B] active:bg-[#B9560B] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";

// الحقول الخطية: بلا إطار صندوقي، خط شعري سفلي يتحول برتقاليًا عند المرور أو التحرير.
export const FIELD =
  "h-8 rounded-none border-x-0 border-t-0 border-b border-b-[#DED8CD] bg-transparent px-0.5 text-[12px] text-[#33322E] shadow-none transition-[border-color] duration-200 placeholder:text-[#7A766C] hover:border-b-[#E8761A] focus-visible:border-b-[#E8761A] focus-visible:ring-0 focus-visible:outline-none md:text-[12px]";

export const FIELD_SELECT =
  "h-8 w-full justify-between rounded-none border-x-0 border-t-0 border-b border-b-[#DED8CD] bg-transparent px-0.5 text-[12px] text-[#33322E] shadow-none transition-[border-color] duration-200 hover:border-b-[#E8761A] focus:border-b-[#E8761A] focus:ring-0 focus-visible:outline-none data-[placeholder]:text-[#7A766C]";

export const FIELD_LABEL = "mb-1 block text-[11px] font-normal text-[#7A766C]";

export const FIELD_HINT = "mt-1 block text-[10.5px] text-[#7A766C]";

// لوحة الفلاتر: متصلة بالجدول من أعلى (بلا خط سفلي ولا زوايا سفلية).
export const FILTER_PANEL = "mt-4 rounded-t-lg rounded-b-none border-[#DED8CD] border-b-0 bg-white !shadow-none";

export const FILTER_PANEL_HEADER = "px-3.5 py-2.5 [&_button]:text-[12px]";

export const FILTER_PANEL_CONTENT = "border-t-0 px-3.5 py-2.5";

export const TH = "h-auto py-2.5 text-[11px] font-semibold tracking-[.2px] text-[#F7F5F0]";

export const TD = "px-2.5 py-[11px]";

// ألوان نصوص الخلايا: أساسي، ثانوي، رقم، رقم مميّز برتقالي، ونص باهت للفراغ.
export const CELL_MAIN = "text-[12px] text-[#33322E]";

export const CELL_SUB = "text-[11px] text-[#7A766C]";

export const CELL_NUM = "num text-[12px]";

export const CELL_ACCENT = "num font-semibold text-[#E8761A]";

export const CELL_EMPTY = "num text-[#9C978B]";

// لوحة الجدول: كتلة واحدة بلا زوايا أو ظل، رأس داكن، وصفوف بخط شعري.
export const LEDGER =
  "ledger-rows overflow-hidden rounded-none border border-[#DED8CD] border-b-0 bg-white !shadow-none [&_thead_tr]:border-b-0 [&_thead_tr]:bg-[#33322E] [&_thead_tr:hover]:bg-[#33322E] [&_thead_th_button]:text-[#F7F5F0] [&_thead_th_button:hover]:text-white [&_tbody_tr]:border-b [&_tbody_tr]:border-[#DED8CD] [&_tbody_tr:hover]:bg-[#FCF9F3]";

// شريط أعلى الجدول (ملخّص الأرقام) وشريطه السفلي (الترقيم) — يُمرَّران لـ DataTable.
export const LEDGER_TOOLBAR = "border-b-0 px-3.5 py-2";

export const LEDGER_FOOTER = "border-[#DED8CD] px-3.5 py-2";