// قراءة الكتالوج للتعديل والأرشفة: المنتجات من /products (مش من أرصدة المخزن).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "@/cashier/api/posApi";
import { catalogApi } from "@/cashier/api/catalogApi";
import { toProductRow } from "@/cashier/lib/productRows";

const LIST_KEY = ["cashier", "catalog", "productList"];

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
