"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/t";

/** §104 — تأكيد الإجراءات الخطرة قبل تنفيذها.
 *
 *  أي زر يفعل شيء لا يمكن التراجع عنه (حذف، إلغاء، خروج، رفض) يمر من هنا.
 *  الزر الافتراضي للتركيز هو «إلغاء» — الخطأ الآمن هو عدم الفعل لا فعله. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = t.confirm,
  cancelLabel = t.cancel,
  onConfirm,
  pending = false,
  destructive = true,
  testid = "confirm-dialog",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  /** أثناء تنفيذ الإجراء نمنع الإغلاق المتكرر ونوقف الأزرار. */
  pending?: boolean;
  destructive?: boolean;
  testid?: string;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return; // لا إغلاق أثناء التنفيذ
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-sm" data-testid={testid}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {destructive && (
              <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-danger" />
            )}
            {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={pending}
            data-testid="confirm-dialog-cancel"
            autoFocus
          >
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
            disabled={pending}
            data-testid="confirm-dialog-confirm"
          >
            {pending ? t.loading : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
