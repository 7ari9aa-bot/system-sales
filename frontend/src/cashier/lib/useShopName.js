import { useAuth } from "@/lib/AuthContext";
import { receiptHeader } from "@/cashier/lib/shopProfile";

/** The shop's real name (the signed-in user's single tenant), the same rule the printed receipt uses. */
export function useShopName() {
  const { user } = useAuth();
  return receiptHeader(user?.tenants?.length === 1 ? user.tenants[0] : null).name;
}
