"use client";

/** Next's route-segment boundary for the dashboard. It catches a crash inside a
 *  page below the shell, so the nav stays usable and the merchant can retry the
 *  view. The layout's own `ErrorBoundary` wraps the shell and so still covers
 *  what this one cannot see — the two are nested, not duplicated. */

import * as React from "react";
import { ErrorState } from "@/components/ui/states";

export default function DashError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-10">
      <ErrorState message={error.message} onRetry={reset} />
    </div>
  );
}
