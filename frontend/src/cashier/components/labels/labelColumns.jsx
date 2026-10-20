import LabelQtyInput from "@/cashier/components/labels/LabelQtyInput";
import { TD, TH } from "@/cashier/components/labels/labelStyles";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// أعمدة جدول طباعة الملصقات: كل منتج سطر، وعدد الملصقات رقم قابل للتحرير داخل الخلية.
export default function labelColumns({ labelsOf, uniformQty, setProductQty }) {
  return [
    {
      key: "name",
      header: "المنتج",
      headerClassName: TH,
      className: TD,
      render: (p) => (
        <span>
          <span className="block font-semibold">{p.name}</span>
          <span className="num mt-0.5 block text-[11px] text-[#7A766C]">
            {p.sku} • {p.brand}
          </span>
        </span>
      ),
    },
    {
      key: "category",
      header: "التصنيف",
      headerClassName: TH,
      className: TD,
      render: (p) => <span className="num text-[12px]">{p.category}</span>,
    },
    {
      key: "variantsCount",
      header: "الألوان والمقاسات",
      headerClassName: TH,
      className: TD,
      align: "center",
      sortValue: (p) => p.variantsCount,
      render: (p) => (
        <span className="num text-[12px]">
          {fmtInt(p.colors.length)} لون • {fmtInt(p.sizes.length)} مقاس • {fmtInt(p.variantsCount)} متغير
        </span>
      ),
    },
    {
      key: "totalStock",
      header: "الرصيد",
      headerClassName: TH,
      className: TD,
      align: "center",
      render: (p) => <span className="num font-semibold">{fmtInt(p.totalStock)}</span>,
    },
    {
      key: "sellPrice",
      header: "سعر البيع",
      headerClassName: TH,
      className: TD,
      align: "end",
      render: (p) => <span className="num font-semibold">{fmtMoney(p.sellPrice)}</span>,
    },
    {
      key: "qty",
      header: "ملصقات لكل متغير",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (p) => {
        const uniform = uniformQty(p);
        return (
          <LabelQtyInput
            value={uniform}
            mixed={uniform === null}
            label={`عدد الملصقات لكل متغير — ${p.name}`}
            onChange={(value) => setProductQty(p, value)}
          />
        );
      },
    },
    {
      key: "labels",
      header: "إجمالي الملصقات",
      headerClassName: TH,
      className: TD,
      sortable: false,
      align: "center",
      render: (p) =>
        labelsOf(p) ? (
          <span className="num font-bold text-[#E8761A]">{fmtInt(labelsOf(p))}</span>
        ) : (
          <span className="text-[#9C978B]">—</span>
        ),
    },
  ];
}