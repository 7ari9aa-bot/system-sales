import { useQuery } from "@tanstack/react-query";
import { catalogApi } from "./catalogApi";
import { BUILT_IN_OPTIONS, normaliseOptions } from "@/applications/apparel/lib/shopOptions";
import { ALL_SHOWN, normaliseScreens } from "@/applications/apparel/lib/stockScreens";

export const SHOP_OPTIONS_KEY = ["shop-options"];

/** The shop's own size sets and colours. Never empty: until the answer arrives, or if it fails, the built-in lists. */
export function useShopOptions() {
  const q = useQuery({
    queryKey: SHOP_OPTIONS_KEY,
    staleTime: 5 * 60 * 1000,
    retry: 1,
    queryFn: async () => normaliseOptions(await catalogApi.shopOptions()),
  });
  return { options: q.data ?? BUILT_IN_OPTIONS, isLoading: q.isLoading };
}

export const STOCK_SCREENS_KEY = ["stock-screens"];

/**
 * Which optional stock screens the shop shows. Never undefined: until the answer arrives, or if it
 * cannot be read, every screen is shown (what the shop had before the switches), so a failed read
 * never takes a screen from its owner.
 */
export function useStockScreens() {
  const q = useQuery({
    queryKey: STOCK_SCREENS_KEY,
    staleTime: 5 * 60 * 1000,
    retry: 1,
    queryFn: async () => normaliseScreens(await catalogApi.stockScreens()),
  });
  return q.data ?? ALL_SHOWN;
}
