"use client";

/** Root-segment boundary: the public and auth pages had no error surface at all,
 *  so a render crash there was a white screen. Dashboard routes are caught by
 *  the nearer `(dash)/error.tsx` and stay inside their shell. */

import * as React from "react";
import { ErrorState } from "@/components/ui/states";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[60dvh] items-center justify-center p-6">
      <ErrorState message={error.message} onRetry={reset} className="w-full max-w-md" />
    </div>
  );
}
