"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DirectionProvider } from "@radix-ui/react-direction";
import { Toaster } from "@/components/ui/toast";

/** Providers العامة: RTL لـRadix + TanStack Query + Toaster. */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnWindowFocus: true, // إعادة جلب في الخلفية
          },
        },
      }),
  );

  return (
    <DirectionProvider dir="rtl">
      <QueryClientProvider client={queryClient}>
        {children}
        <Toaster />
      </QueryClientProvider>
    </DirectionProvider>
  );
}
