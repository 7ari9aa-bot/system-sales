// هيكل شاشات الجداول: خلفية رملية، شريط عنوان، ومنطقة محتوى مضبوطة الهوامش.
export default function LedgerPage({ hero, children }) {
  return (
    <div className="-mx-2 -my-2 min-h-[calc(100vh-1rem)] bg-[#F7F5F0] pb-6 text-[#33322E] sm:-mx-3">
      {hero}
      <div className="px-7">{children}</div>
    </div>
  );
}