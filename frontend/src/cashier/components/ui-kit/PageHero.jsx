import { Image } from "@/cashier/components/ui/image";

// شريط عنوان الشاشة: صورة خلفية مع تظليل داكن، عنوان ووصف، وأزرار الإجراءات.
// على الشاشات الصغيرة يترتب المحتوى عموديًا حتى لا تُقتطع الأزرار.
export default function PageHero({ image, imageAlt, title, description, children }) {
  return (
    <header className="relative min-h-[150px] overflow-hidden bg-[#33322E]">
      <Image src={image} alt={imageAlt} fittingType="fill" className="absolute inset-0 h-full w-full" />
      <div className="absolute inset-0 bg-[linear-gradient(270deg,rgba(51,50,46,0.88),rgba(51,50,46,0.55)_60%,rgba(51,50,46,0.25))]" />

      <div className="relative flex min-h-[150px] flex-col justify-center gap-3 px-5 py-4 sm:px-7 lg:flex-row lg:items-center lg:justify-between lg:gap-6">
        <div>
          <h1 className="font-heading text-[15px] font-semibold leading-snug text-white">{title}</h1>
          {description && <p className="mt-1.5 max-w-[560px] text-[12px] leading-relaxed text-[#EDE6D8]">{description}</p>}
        </div>

        {children && <div className="flex flex-wrap items-center gap-2 lg:shrink-0">{children}</div>}
      </div>
    </header>
  );
}