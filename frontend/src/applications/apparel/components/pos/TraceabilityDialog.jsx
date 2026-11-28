import React, { useState, useEffect, useRef } from "react";
import { Button } from "@/applications/apparel/components/ui/button";
import { Input } from "@/applications/apparel/components/ui/input";
import { Badge } from "@/applications/apparel/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/applications/apparel/components/ui/dialog";
import { Barcode, Calendar, Check, Hash, Trash2 } from "lucide-react";

export function TraceabilityDialogBody({
  variant,
  quantity = 1,
  traceInfo,
  onConfirm,
  onBack,
  pending = false,
}) {
  const mode = traceInfo?.mode || "none";
  const [selectedSerials, setSelectedSerials] = useState([]);
  const [currentSerialInput, setCurrentSerialInput] = useState("");
  const [selectedLotId, setSelectedLotId] = useState(
    traceInfo?.lots?.[0]?.id || ""
  );
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (mode === "serial" && inputRef.current) {
      inputRef.current.focus();
    }
  }, [mode]);

  function handleAddSerial(code) {
    const clean = (code || currentSerialInput).trim();
    if (!clean) return;
    setError("");

    if (selectedSerials.includes(clean)) {
      setError("الرقم التسلسلي مضاف بالفعل");
      return;
    }
    if (selectedSerials.length >= quantity) {
      setError(`تم استيفاء العدد المطلوب (${quantity})`);
      return;
    }

    // Optional validation against known available serials
    const availableCodes = (traceInfo?.serials || []).map((s) => s.serial_code);
    if (availableCodes.length > 0 && !availableCodes.includes(clean)) {
      setError("الرقم التسلسلي غير موجود ضمن الأرصدة المتاحة في المخزن");
      return;
    }

    setSelectedSerials((prev) => [...prev, clean]);
    setCurrentSerialInput("");
  }

  function handleRemoveSerial(code) {
    setSelectedSerials((prev) => prev.filter((s) => s !== code));
    setError("");
  }

  function handleConfirm() {
    if (mode === "serial") {
      if (selectedSerials.length !== quantity) {
        setError(`يرجى تحديد ${quantity} رقم تسلسلي (المحدد حالياً: ${selectedSerials.length})`);
        return;
      }
      onConfirm({ serialCodes: selectedSerials });
    } else if (mode === "batch") {
      if (!selectedLotId) {
        setError("يرجى اختيار رقم التشغيلة/الدفعة");
        return;
      }
      const chosen = (traceInfo?.lots || []).find((l) => l.id === selectedLotId);
      onConfirm({ lotId: selectedLotId, lotCode: chosen?.lot_code });
    }
  }

  return (
    <div className="space-y-4 text-sm" dir="rtl">
      <div className="rounded-xl border border-border bg-muted/40 p-3">
        <div className="flex items-center justify-between font-bold">
          <span>الصنف: {variant?.productName || variant?.name}</span>
          <Badge variant="outline" className="gap-1">
            <Hash className="h-3 w-3" />
            الكمية: {quantity}
          </Badge>
        </div>
        {variant?.sku ? (
          <p className="mt-1 text-xs text-muted-foreground">الكود: {variant.sku}</p>
        ) : null}
      </div>

      {mode === "serial" ? (
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">
              مسح أو إدخال الرقم التسلسلي ({selectedSerials.length}/{quantity})
            </label>
            <div className="flex gap-2">
              <Input
                ref={inputRef}
                value={currentSerialInput}
                onChange={(e) => setCurrentSerialInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAddSerial();
                  }
                }}
                placeholder="امسح الباركود أو اكتب السيريال…"
                disabled={selectedSerials.length >= quantity || pending}
                className="font-mono"
              />
              <Button
                type="button"
                variant="secondary"
                disabled={!currentSerialInput.trim() || selectedSerials.length >= quantity || pending}
                onClick={() => handleAddSerial()}
              >
                إضافة
              </Button>
            </div>
          </div>

          {/* Selected Serials List */}
          {selectedSerials.length > 0 ? (
            <div className="space-y-1">
              <span className="text-xs font-semibold text-muted-foreground">الأرقام المحددة:</span>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto p-1 rounded-lg border border-border bg-background">
                {selectedSerials.map((s) => (
                  <Badge key={s} variant="secondary" className="gap-1 font-mono text-xs py-1">
                    <Barcode className="h-3 w-3 text-muted-foreground" />
                    {s}
                    <button
                      type="button"
                      onClick={() => handleRemoveSerial(s)}
                      className="text-muted-foreground hover:text-destructive mr-1"
                      title="إزالة"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {/* Available serials fast-pick list */}
          {traceInfo?.serials?.length > 0 ? (
            <div className="space-y-1">
              <span className="text-xs font-semibold text-muted-foreground">
                الأرقام المتاحة بالمخزن (انقر للاختيار):
              </span>
              <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto p-1">
                {traceInfo.serials
                  .filter((s) => !selectedSerials.includes(s.serial_code))
                  .map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      disabled={selectedSerials.length >= quantity}
                      onClick={() => handleAddSerial(s.serial_code)}
                      className="inline-flex items-center gap-1 rounded border border-border bg-muted/50 px-2 py-0.5 text-xs font-mono hover:bg-primary/10 hover:border-primary disabled:opacity-40"
                    >
                      {s.serial_code}
                    </button>
                  ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {mode === "batch" ? (
        <div className="space-y-2">
          <label className="text-xs font-semibold text-muted-foreground block">
            اختر الدفعة / التشغيلة (مرتبة حسب الأقرب انتهاءً FEFO):
          </label>
          <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {(traceInfo?.lots || []).map((lot, idx) => {
              const isSelected = selectedLotId === lot.id;
              const expDate = lot.expires_at ? new Date(lot.expires_at).toLocaleDateString("ar-EG-u-nu-latn") : null;
              return (
                <div
                  key={lot.id}
                  onClick={() => setSelectedLotId(lot.id)}
                  className={`flex cursor-pointer items-center justify-between rounded-xl border p-2.5 transition-colors ${
                    isSelected
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2 font-bold font-mono">
                      <span>{lot.lot_code}</span>
                      {idx === 0 ? (
                        <Badge variant="outline" className="text-[10px] bg-emerald-50 text-emerald-700 border-emerald-200">
                          الأقرب انتهاءً (موصى به)
                        </Badge>
                      ) : null}
                    </div>
                    {expDate ? (
                      <p className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Calendar className="h-3 w-3" />
                        تاريخ الانتهاء: {expDate}
                      </p>
                    ) : null}
                  </div>
                  {isSelected ? <Check className="h-4 w-4 text-primary" /> : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-xs font-semibold text-destructive">
          {error}
        </p>
      ) : null}

      <div className="flex gap-2 pt-2">
        <Button variant="outline" className="flex-1" onClick={onBack} disabled={pending}>
          إلغاء
        </Button>
        <Button
          className="flex-1 font-bold"
          disabled={
            pending ||
            (mode === "serial" && selectedSerials.length !== quantity) ||
            (mode === "batch" && !selectedLotId)
          }
          onClick={handleConfirm}
        >
          {pending ? "جارٍ الحفظ…" : "تأكيد واستمرار"}
        </Button>
      </div>
    </div>
  );
}

export default function TraceabilityDialog({
  open,
  onOpenChange,
  variant,
  quantity = 1,
  traceInfo,
  onConfirm,
  pending = false,
}) {
  const mode = traceInfo?.mode || "none";
  const title =
    mode === "serial"
      ? "تحديد الرقم التسلسلي (Serial Number)"
      : "تحديد رقم الدفعة والتشغيلة (Batch / Lot)";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{title}</DialogTitle>
          <DialogDescription>
            يتطلب هذا الصنف تتبعاً دقيقاً لإتمام عملية البيع
          </DialogDescription>
        </DialogHeader>
        <TraceabilityDialogBody
          variant={variant}
          quantity={quantity}
          traceInfo={traceInfo}
          onConfirm={onConfirm}
          onBack={() => onOpenChange(false)}
          pending={pending}
        />
      </DialogContent>
    </Dialog>
  );
}
