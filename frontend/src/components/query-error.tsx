"use client";

/** The alert a page renders when its reads failed, as opposed to the empty
 *  state it renders when they came back with nothing. The two are different
 *  claims to a merchant: "لا يوجد مخزون" on an HTTP 500 tells them to buy stock
 *  they already have.
 *
 *  Pages gate on `isError` themselves today; this is the shared answer so the
 *  copy, the `role="alert"` hook and the retry all read the same everywhere. */

import * as React from "react";
import { ErrorState } from "@/components/ui/states";
import { t } from "@/lib/t";

type QueryLike = { error: Error | null; refetch: () => unknown };

export function QueryErrorState({ queries }: { queries: QueryLike[] }) {
  const failed = queries.filter((q) => q.error !== null);
  const message = failed.map((q) => q.error?.message).find(Boolean) ?? t.somethingWentWrong;

  return <ErrorState message={message} onRetry={() => failed.forEach((q) => q.refetch())} />;
}
