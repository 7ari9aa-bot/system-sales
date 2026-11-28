import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Role codes the backend returns, with the Arabic label the shop sees. */
export const ROLE_LABEL = { owner: "المالك", manager: "مدير", staff: "كاشير" };

/** The real members of this shop (read only). Adding or removing people happens in the main Sales OS settings. */
export function useTenantUsers() {
  return useQuery({
    queryKey: ["cashier", "tenant-users"],
    queryFn: async () => ((await api("/users")) ?? []).map((u) => ({ id: u.id, name: u.full_name || u.email, email: u.email, role: u.role_code })),
  });
}
