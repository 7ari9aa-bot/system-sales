import React from "react";
import { Button } from "@/components/ui/button";
import { canReopen } from "@/cashier/lib/activitySetup";
import { useActivitySetup, useReopenActivitySetup } from "@/cashier/api/useActivitySetup";

/**
 * In the shop's settings: lets the owner answer "what kind of shop is this?" again. It shows only
 * once the setup was answered or skipped, and only to someone the server lets write settings (a
 * cashier is refused by the server and sees an error, never a changed shop). Reopening changes
 * nothing by itself; when the owner confirms, only the settings they never touched are filled.
 */
export default function ReopenActivitySetup() {
  const { raw } = useActivitySetup();
  const reopen = useReopenActivitySetup();
  if (!canReopen(raw)) return null;
  return (
    <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border p-3" dir="rtl">
      <div className="text-sm">
        <div className="font-medium">إعداد النشاط</div>
        <div className="text-muted-foreground">
          اختار نوع نشاطك من الأول. مش هيغيّر أي إعداد انت ظبطته قبل كده.
        </div>
        {reopen.isError && (
          <div role="alert" className="mt-1 text-destructive">
            معرفناش نفتحه. اتأكد إنك مالك المحل وجرّب تاني.
          </div>
        )}
      </div>
      <Button type="button" variant="outline" disabled={reopen.isPending} onClick={() => reopen.mutate()}>
        {reopen.isPending ? "ثانية..." : "إعادة إعداد النشاط"}
      </Button>
    </div>
  );
}
