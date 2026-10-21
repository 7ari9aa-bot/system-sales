import { Image } from "@/cashier/components/ui/image";
import { INVENTORY_STATUS, fmtInt, fmtMoneyShort } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const STATUS_TONE = { in: "text-emerald-700", low: "text-amber-700", out: "text-rose-700" };

// بطاقة منتج واحدة: صورة، الاسم، شارة التوفر، الكود، والسعر والرصيد وعدد التركيبات.
export default function ProductCard({ product, onOpen }) {
  const status = INVENTORY_STATUS[product.statusValue] ?? INVENTORY_STATUS.in;

  return (
    <button
      type="button"
      onClick={() => onOpen(product)}
      className="flex cursor-pointer flex-col overflow-hidden rounded-2xl border border-[#E3DED4] bg-white text-start shadow-[0_1px_3px_rgba(59,58,54,.06)] transition-[border-color,box-shadow] [transition-duration:250ms] hover:border-[#E8761A] hover:shadow-[0_10px_24px_-12px_rgba(232,118,26,.35)] focus-visible:border-[#E8761A] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]"
    >
      {product.image ? (
        <Image src={product.image} alt={product.name} className="aspect-[4/3] w-full bg-[#EDE9E0] object-cover" />
      ) : (
        // No product photo is stored yet: show a plain placeholder, never somebody else's picture.
        <div aria-hidden="true" className="flex aspect-[4/3] w-full items-center justify-center bg-[#EDE9E0] text-4xl font-bold text-[#B8B2A4]">
          {String(product.name ?? "").trim().charAt(0)}
        </div>
      )}

      <div className="flex flex-col gap-2.5 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[15px] font-semibold leading-snug">{product.name}</span>
          <span
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border border-[#C7C2B8] bg-[#F4F1EC] px-2.5 py-[3px] text-[11px] font-semibold",
              STATUS_TONE[product.statusValue] ?? "text-[#3B3A36]",
            )}
          >
            {status.label}
          </span>
        </div>

        <span className="num text-[11px] text-[#7A766C]">{product.sku}</span>

        <div className="grid grid-cols-3 gap-2 border-t border-[#EFEBE2] pt-2.5">
          <Cell label="السعر" value={fmtMoneyShort(product.price)} />
          <Cell label="الرصيد" value={fmtInt(product.stock)} />
          <Cell label="التركيبات" value={fmtInt(product.variantsCount)} />
        </div>
      </div>
    </button>
  );
}

function Cell({ label, value }) {
  return (
    <span className="flex flex-col gap-0.5 text-[10px] text-[#9A958A]">
      {label}
      <b className="num text-[14px] font-semibold text-[#3B3A36]">{value}</b>
    </span>
  );
}