import { Image } from "@/cashier/components/ui/image";

// شريط عنوان الشاشة: صورة خلفية مع تظليل داكن، عنوان ووصف، وأزرار الإجراءات.
// على الشاشات الصغيرة يترتب المحتوى عموديًا حتى لا تُقتطع الأزرار.
export default function PageHero({ image, imageAlt, title, description, children }) {
  return (
    <header className="relative min-h-[150px] overflow-hidden bg-[#33322E]">
      <Image src={image} alt={imageAlt} fittingType="fill" className="absolute inset-0 h-full w-full object-cover" />
      <div className="absolute inset-0 bg-black/60" />
      <div className="absolute inset-0 bg-[linear-gradient(270deg,rgba(35,32,28,0.92)_0%,rgba(35,32,28,0.85)_50%,rgba(35,32,28,0.75)_100%)]" />

      <div className="relative z-10 flex min-h-[150px] flex-col justify-center gap-3 px-5 py-4 sm:px-7 lg:flex-row lg:items-center lg:justify-between lg:gap-6">
        <div>
          <h1 className="font-heading text-[17px] sm:text-[19px] font-bold leading-snug text-white drop-shadow-xs">{title}</h1>
          {description && <p className="mt-1.5 max-w-[580px] text-[12.5px] leading-relaxed text-[#F3EFE6] drop-shadow-xs">{description}</p>}
        </div>

        {children && <div className="flex flex-wrap items-center gap-2.5 lg:shrink-0">{children}</div>}
      </div>
    </header>
  );
}