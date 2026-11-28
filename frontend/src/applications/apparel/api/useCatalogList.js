// قراءة الكتالوج للتعديل والأرشفة: المنتجات من /products (مش من أرصدة المخزن).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "@/applications/apparel/api/posApi";
import { catalogApi } from "@/applications/apparel/api/catalogApi";
import { toProductRow } from "@/applications/apparel/lib/productRows";

const LIST_KEY = ["cashier", "catalog", "productList"];
export const PAGE_SIZE = 50;

export function useCatalogProducts() {
  return useQuery({
    queryKey: LIST_KEY,
    staleTime: 30_000,
    queryFn: async () => {
      const res = await posApi.products();
      const list = Array.isArray(res) ? res : (res?.items ?? []);
      return list.map(toProductRow);
    },
  });
}

/**
 * صفحة من الكتالوج من السيرفر: البحث والفلترة والترتيب والعدّ كلهم في قاعدة البيانات.
 * قبل كده الشاشة كانت بتجيب أول 500 منتج وبتدوّر فيهم، فمحل عنده 3000 منتج مايشوفش الباقي.
 */
export function useCatalogPage(filters, page = 0, pageSize = PAGE_SIZE) {
  const params = {
    term: filters?.term ?? "",
    status: filters?.status ?? "",
    categoryId: filters?.categoryId ?? "",
    brandId: filters?.brandId ?? "",
    season: filters?.season ?? "",
    sort: filters?.sort ?? "newest",
    limit: pageSize,
    offset: page * pageSize,
  };
  return useQuery({
    queryKey: [...LIST_KEY, "page", params],
    staleTime: 15_000,
    placeholderData: (previous) => previous,
    queryFn: async () => {
      const res = await catalogApi.productsPage(params);
      const items = Array.isArray(res) ? res : (res?.items ?? []);
      return {
        rows: items.map(toProductRow),
        total: Number(res?.total ?? items.length),
        hasMore: Boolean(res?.has_more),
      };
    },
  });
}

/** أرشفة منتج أو رجوعه للبيع: نفس الـPATCH، والحالة هي اللي بتتغيّر. */
export function useSetProductStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }) => catalogApi.updateProduct(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIST_KEY });
      qc.invalidateQueries({ queryKey: ["cashier", "catalog"] });
    },
  });
}
